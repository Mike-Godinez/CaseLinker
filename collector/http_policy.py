"""Honest collector identity and robots.txt enforcement.

Every listing or article request goes through ``acquire`` first. A disallowed
path is not requested. A 403 or a robots.txt fetch that is itself blocked
stops the host. Crawl-delay is the minimum gap between requests to that host.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

COLLECTOR_UA = (
    "CaseLinkerCollector/1.0 "
    "(+https://github.com/mrinaalr/CaseLinker; public press-release harvest)"
)

# Used when a host publishes no Crawl-delay. Callers may wait longer.
POLITE_GAP_S = 1.5


class RobotsDenied(RuntimeError):
    """robots.txt disallows this URL. Do not request it."""


class BlockedHost(RuntimeError):
    """The host returned 403 or a robots.txt block. Stop this source."""

    def __init__(self, url: str, status: int) -> None:
        self.url = url
        self.status = status
        super().__init__(f"blocked {status} {url}")


@dataclass
class _HostRules:
    parser: RobotFileParser
    crawl_delay: float
    globs: tuple[str, ...] = ()
    blocked: bool = False


@dataclass
class HostPolicy:
    """Cache robots.txt per origin and pace requests."""

    session_get: object
    gap_s: float = POLITE_GAP_S
    _rules: dict[str, _HostRules] = field(default_factory=dict)
    _last: dict[str, float] = field(default_factory=dict)

    def headers(self, url: str, *, accept: str | None = None) -> dict[str, str]:
        origin = _origin(url)
        hdrs = {
            "User-Agent": COLLECTOR_UA,
            "Accept": accept or "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "From": "caselinker-collector@users.noreply.github.com",
        }
        if origin:
            hdrs["Referer"] = origin + "/"
        return hdrs

    def acquire(self, url: str) -> None:
        """Wait out Crawl-delay, then allow the request or raise."""
        rules = self._rules_for(url)
        host = _host(url)
        if rules.blocked:
            raise BlockedHost(url, 403)
        path = urlparse(url).path or "/"
        if any(_glob_match(pattern, path) for pattern in rules.globs):
            raise RobotsDenied(f"robots.txt disallows {url}")
        if not rules.parser.can_fetch(COLLECTOR_UA, url):
            raise RobotsDenied(f"robots.txt disallows {url}")
        delay = max(self.gap_s, rules.crawl_delay)
        elapsed = time.monotonic() - self._last.get(host, 0.0)
        if host in self._last and elapsed < delay:
            time.sleep(delay - elapsed)
        self._last[host] = time.monotonic()

    def note_status(self, url: str, status: int) -> None:
        if status == 403:
            host = _host(url)
            if host in self._rules:
                self._rules[host].blocked = True
            raise BlockedHost(url, status)

    def _rules_for(self, url: str) -> _HostRules:
        host = _host(url)
        cached = self._rules.get(host)
        if cached is not None:
            return cached
        origin = _origin(url)
        robots_url = f"{origin}/robots.txt"
        # The robots file itself is not subject to its own Disallow list.
        self._last[host] = time.monotonic()
        try:
            response = self.session_get(robots_url, self.headers(robots_url, accept="text/plain,*/*"))
        except Exception as exc:
            raise BlockedHost(robots_url, 0) from exc
        status = int(getattr(response, "status_code", 0) or 0)
        if status == 403:
            rules = _HostRules(parser=_empty_parser(origin), crawl_delay=0.0, blocked=True)
            self._rules[host] = rules
            raise BlockedHost(robots_url, 403)
        body = ""
        if status == 200:
            body = getattr(response, "text", "") or ""
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(body.splitlines())
        rules = _HostRules(
            parser=parser,
            crawl_delay=_crawl_delay(body),
            globs=_glob_disallows(body),
        )
        self._rules[host] = rules
        return rules


def _host(url: str) -> str:
    return urlparse(url).netloc.lower()


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _empty_parser(origin: str) -> RobotFileParser:
    parser = RobotFileParser()
    parser.set_url(f"{origin}/robots.txt")
    parser.parse(["User-agent: *", "Disallow:"])
    return parser


def _glob_disallows(body: str) -> tuple[str, ...]:
    """Disallow rules that contain ``*``, which RobotFileParser does not apply."""
    found: list[str] = []
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().lower() == "disallow" and "*" in value:
            found.append(value.strip())
    return tuple(found)


def _glob_match(pattern: str, path: str) -> bool:
    regex = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
    # ``*.pdf`` is written against the whole path, not only a full-string match
    # of a leading star, so also accept a match anywhere in the path.
    if pattern.startswith("*"):
        regex = re.escape(pattern).replace(r"\*", ".*") + "$"
    return re.search(regex, path) is not None


def _crawl_delay(body: str) -> float:
    """Crawl-delay for User-agent: * (non-standard, but published by these hosts)."""
    agent = "*"
    delay = 0.0
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            agent = value.lower()
        elif key == "crawl-delay" and agent in {"*", COLLECTOR_UA.lower()}:
            try:
                delay = float(value)
            except ValueError:
                continue
    return max(0.0, delay)

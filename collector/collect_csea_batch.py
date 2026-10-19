#!/usr/bin/env python3
"""Harvest child-exploitation case URLs for the nine-source batch.

Colorado CBI is not requested: its robots.txt returns 403 to this collector.
Wisconsin DOJ and New Zealand DIA are out of scope.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from case_release_filter import classify_release
    from http_policy import BlockedHost, HostPolicy, RobotsDenied
except ImportError:
    from collector.case_release_filter import classify_release
    from collector.http_policy import BlockedHost, HostPolicy, RobotsDenied

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "collector" / "sources"
REPORT = ROOT / "collector_output" / "csea_batch_report.json"
SPARQL = "https://caselinker.up.railway.app/sparql"

MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)


def _get(url: str, headers: dict[str, str]):
    return requests.get(url, headers=headers, timeout=45, allow_redirects=True)


POLICY = HostPolicy(session_get=_get)


def fetch(url: str, *, accept: str | None = None) -> requests.Response:
    POLICY.acquire(url)
    response = requests.get(
        url,
        headers=POLICY.headers(url, accept=accept),
        timeout=45,
        allow_redirects=True,
    )
    if response.status_code == 403:
        POLICY.note_status(url, 403)
    return response


def text_of(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True)


def page_links(html: str, page_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        absolute = urljoin(page_url, href).split("#", 1)[0]
        if absolute in seen:
            continue
        seen.add(absolute)
        found.append((absolute, anchor.get_text(" ", strip=True)))
    return found


def classify_html(title: str, html: str) -> str:
    return classify_release(title, text_of(html))


class SourceStop(Exception):
    def __init__(self, source: str, reason: str) -> None:
        self.source = source
        self.reason = reason
        super().__init__(f"{source}: {reason}")


def guarded(source: str, url: str) -> requests.Response | None:
    try:
        response = fetch(url)
    except RobotsDenied as exc:
        print(f"  [robots] {exc}", file=sys.stderr)
        return None
    except BlockedHost as exc:
        raise SourceStop(source, str(exc)) from exc
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        print(f"  [http {response.status_code}] {url}", file=sys.stderr)
        return None
    return response


def harvest_alert() -> tuple[list[str], list[dict]]:
    kept: list[str] = []
    notes: list[dict] = []
    page = 1
    while page <= 20:
        url = (
            "https://alert-ab.ca/wp-json/wp/v2/posts"
            f"?categories=12&per_page=100&page={page}"
            "&_fields=link,title,content,date"
        )
        response = guarded("ALERT ICE", url)
        if response is None:
            break
        posts = response.json()
        if not isinstance(posts, list) or not posts:
            break
        for post in posts:
            title = BeautifulSoup(post.get("title", {}).get("rendered", ""), "html.parser").get_text(" ", strip=True)
            body = post.get("content", {}).get("rendered", "")
            link = (post.get("link") or "").split("?")[0]
            if link and len(text_of(body)) < 80:
                article = guarded("ALERT ICE", link)
                if article is not None:
                    body = article.text
            decision = classify_html(title, body)
            notes.append({"source": "ALERT ICE", "url": link, "title": title, "decision": decision, "date": post.get("date")})
            if decision == "keep" and link:
                kept.append(link)
        if len(posts) < 100:
            break
        page += 1
    return kept, notes


def harvest_maryland() -> tuple[list[str], list[dict]]:
    response = guarded("MDSP", "https://mdsp.maryland.gov/sitemap.xml")
    if response is None:
        return [], []
    locs = re.findall(r"<loc>(.*?)</loc>", response.text)
    candidates = [
        loc for loc in locs
        if "/about-us/newsroom/" in loc
        and ("child-pornography" in loc or "sexual-solicitation" in loc)
    ]
    kept, notes = [], []
    for url in candidates:
        article = guarded("MDSP", url)
        if article is None:
            continue
        title = BeautifulSoup(article.text, "html.parser").title
        title_text = title.get_text(" ", strip=True) if title else url
        decision = classify_html(title_text, article.text)
        notes.append({"source": "MDSP", "url": url, "title": title_text, "decision": decision})
        if decision == "keep":
            kept.append(url)
    return kept, notes


def harvest_nova() -> tuple[list[str], list[dict]]:
    kept, notes = [], []
    page = 1
    while page <= 10:
        url = (
            "https://novadcicac.vsp.virginia.gov/wp-json/wp/v2/posts"
            f"?categories=3&per_page=100&page={page}&_fields=link,title,content,date"
        )
        response = guarded("NOVA ICAC", url)
        if response is None:
            break
        posts = response.json()
        if not isinstance(posts, list) or not posts:
            break
        for post in posts:
            link = (post.get("link") or "").split("?")[0]
            if urlparse(link).netloc.lower() != "novadcicac.vsp.virginia.gov":
                notes.append({"source": "NOVA ICAC", "url": link, "title": "", "decision": "offhost"})
                continue
            title = BeautifulSoup(post.get("title", {}).get("rendered", ""), "html.parser").get_text(" ", strip=True)
            decision = classify_html(title, post.get("content", {}).get("rendered", ""))
            notes.append({"source": "NOVA ICAC", "url": link, "title": title, "decision": decision})
            if decision == "keep":
                kept.append(link)
        if len(posts) < 100:
            break
        page += 1
    return kept, notes


_SCOT_SLUG = re.compile(
    r"indecent-image|against-children|child-sexual|online-child|"
    r"sexual-offence|sexual-offending|child-abuse",
    re.I,
)


def harvest_scotland() -> tuple[list[str], list[dict]]:
    kept, notes = [], []
    for year in range(2022, 2027):
        for month in MONTHS:
            index = f"https://www.scotland.police.uk/what-s-happening/news/{year}/{month}/"
            response = guarded("SCOTLAND POLICE", index)
            if response is None:
                continue
            for url, title in page_links(response.text, index):
                path = urlparse(url).path.lower()
                if "/what-s-happening/news/2020/" in path or "/what-s-happening/news/2021/" in path:
                    continue
                if not _SCOT_SLUG.search(path):
                    continue
                article = guarded("SCOTLAND POLICE", url)
                if article is None:
                    continue
                decision = classify_html(title, article.text)
                notes.append({"source": "SCOTLAND POLICE", "url": url, "title": title, "decision": decision})
                if decision == "keep":
                    kept.append(url)
            print(f"  scotland {year}-{month} kept={len(kept)}", file=sys.stderr)
    return kept, notes


def _paged_links(source: str, start: str, same_prefix: str, page_ok) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen_pages: set[str] = set()
    queue = [start]
    while queue and len(seen_pages) < 80:
        page = queue.pop(0)
        if page in seen_pages:
            continue
        seen_pages.add(page)
        response = guarded(source, page)
        if response is None:
            continue
        for url, title in page_links(response.text, page):
            path = urlparse(url).path.lower()
            if "/search" in path:
                continue
            if page_ok(url, title):
                found.append((url, title))
            elif url.startswith(same_prefix) and url not in seen_pages and _is_more_listing(url, start):
                queue.append(url)
    return found


def _is_more_listing(url: str, start: str) -> bool:
    """Follow listing pagers only. Article URLs are not pagers."""
    if url.split("#", 1)[0] == start.split("#", 1)[0]:
        return False
    path = urlparse(url).path.lower()
    start_path = urlparse(start).path.lower().rstrip("/")
    if not path.startswith(start_path):
        return False
    return "/page/" in path or "start=" in url.lower()


def harvest_keyword_listing(source: str, start: str, predicate) -> tuple[list[str], list[dict]]:
    pairs = _paged_links(source, start, start.split("?")[0], predicate)
    kept, notes = [], []
    seen: set[str] = set()
    for url, title in pairs:
        if url in seen:
            continue
        seen.add(url)
        article = guarded(source, url)
        if article is None:
            continue
        decision = classify_html(title, article.text)
        notes.append({"source": source, "url": url, "title": title, "decision": decision})
        if decision == "keep":
            kept.append(url)
    return kept, notes


def harvest_singapore() -> tuple[list[str], list[dict]]:
    """The news hub is a POST archive at /api/GetNews. /search is not used."""
    api = "https://www.police.gov.sg/api/GetNews"
    POLICY.acquire(api)
    response = requests.post(
        api,
        json={"page": 1, "itemsPerPage": 100},
        headers={**POLICY.headers(api, accept="application/json"), "Content-Type": "application/json"},
        timeout=60,
    )
    if response.status_code == 403:
        raise SourceStop("SPF", "GetNews returned 403")
    response.raise_for_status()
    kept, notes = [], []
    for item in response.json().get("items") or []:
        path = (item.get("url") or "").lower()
        title = item.get("title") or ""
        blob = f"{path} {title}".lower()
        if "child_sexual" not in path and "child_abuse" not in path and "child-sexual" not in path and "child-abuse" not in path:
            if not (("child" in blob or "chld" in blob) and any(
                token in blob for token in ("sexual", "sxual", "exploit", "abuse", "porn")
            )):
                continue
        url = urljoin("https://www.police.gov.sg", item["url"])
        article = guarded("SPF", url)
        if article is None:
            continue
        decision = classify_html(title, article.text)
        notes.append({"source": "SPF", "url": url, "title": title, "decision": decision})
        if decision == "keep":
            kept.append(url)
    return kept, notes


def harvest_virginia() -> tuple[list[str], list[dict]]:
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    start = 0
    empty = 0
    while start <= 5000 and empty < 2:
        url = "https://www.oag.state.va.us/media-center/news-releases"
        if start:
            url += f"?start={start}"
        response = guarded("VA AG", url)
        if response is None:
            break
        ids = re.findall(r"/media-center/news-releases/(\d+)-", response.text)
        if not ids:
            empty += 1
        else:
            empty = 0
        for link, title in page_links(response.text, response.url):
            path = urlparse(link).path.lower()
            if not re.search(r"/media-center/news-releases/\d+-", path):
                continue
            if link in seen:
                continue
            blob = f"{path} {title}".lower()
            if not any(token in blob for token in (
                "child", "porn", "exploit", "indecent", "icac", "minor", "sexual",
            )):
                continue
            seen.add(link)
            candidates.append((link, title))
        start += 25
        print(f"  virginia start={start} candidates={len(candidates)}", file=sys.stderr)
    return _fetch_candidates("VA AG", candidates)


def harvest_minnesota() -> tuple[list[str], list[dict]]:
    response = guarded("MN BCA", "https://dps.mn.gov/sitemap.xml")
    if response is None:
        return [], []
    candidates = []
    for loc in re.findall(r"<loc>(.*?)</loc>", response.text):
        path = urlparse(loc).path.lower()
        if not path.startswith("/news/"):
            continue
        if path.endswith(".pdf") or path.rstrip("/") in {"/news", "/news/releases"}:
            continue
        if any(token in path for token in ("child", "porn", "exploit", "predator", "icac", "sexual")):
            candidates.append((loc, loc.rsplit("/", 1)[-1].replace("-", " ")))
    print(f"  minnesota candidates={len(candidates)}", file=sys.stderr)
    return _fetch_candidates("MN BCA", candidates)


def _fetch_candidates(source: str, candidates: list[tuple[str, str]]) -> tuple[list[str], list[dict]]:
    kept, notes = [], []
    seen: set[str] = set()
    for url, title in candidates:
        if url in seen:
            continue
        seen.add(url)
        article = guarded(source, url)
        if article is None:
            continue
        decision = classify_html(title, article.text)
        notes.append({"source": source, "url": url, "title": title, "decision": decision})
        if decision == "keep":
            kept.append(url)
    return kept, notes


def harvest_nbi() -> tuple[list[str], list[dict]]:
    def pred(url: str, title: str) -> bool:
        path = urlparse(url).path.lower()
        if "/press_releases/" not in path or path.rstrip("/").endswith("press_releases"):
            return False
        if "/page/" in path:
            return False
        blob = f"{path} {title}".lower()
        return any(token in blob for token in (
            "child", "csaem", "osaec", "sexual", "porn", "11930", "exploit",
        ))

    return harvest_keyword_listing("NBI", "https://nbi.gov.ph/press_releases/", pred)


def harvest_garda() -> tuple[list[str], list[dict]]:
    root = "https://www.garda.ie/en/about-us/our-departments/office-of-corporate-communications/press-releases/"
    indexes = [root]
    seen_indexes: set[str] = set()
    articles: list[tuple[str, str]] = []
    while indexes and len(seen_indexes) < 2500:
        page = indexes.pop(0)
        if page in seen_indexes:
            continue
        seen_indexes.add(page)
        response = guarded("GARDA", page)
        if response is None:
            continue
        for url, title in page_links(response.text, page):
            if not url.startswith(root):
                continue
            rest = url[len(root):].strip("/")
            parts = [part for part in rest.split("/") if part]
            if not parts:
                continue
            if "pagenumber=" in url.lower() or (len(parts) <= 2 and not parts[-1].endswith(".html")):
                if url not in seen_indexes:
                    indexes.append(url if url.endswith("/") or "pagenumber=" in url.lower() else url + "/")
            elif parts[-1].endswith(".html"):
                blob = f"{url} {title}".lower()
                if any(token in blob for token in (
                    "child", "porn", "sexual", "exploit", "indecent", "minor", "girl", "boy",
                )):
                    articles.append((url, title))
        print(f"  garda indexes={len(seen_indexes)} queued={len(indexes)} articles={len(articles)}", file=sys.stderr)
    kept, notes = [], []
    seen: set[str] = set()
    for url, title in articles:
        if url in seen:
            continue
        seen.add(url)
        article = guarded("GARDA", url)
        if article is None:
            continue
        decision = classify_html(title, article.text)
        notes.append({"source": "GARDA", "url": url, "title": title, "decision": decision})
        if decision == "keep":
            kept.append(url)
        if len(seen) % 25 == 0:
            print(f"  garda read={len(seen)} kept={len(kept)}", file=sys.stderr)
    return kept, notes


def sparql_urls(fragment: str) -> set[str]:
    query = f"""
PREFIX dcterms: <http://purl.org/dc/terms/>
SELECT ?url WHERE {{
  ?s dcterms:source ?url .
  FILTER(CONTAINS(LCASE(STR(?url)), "{fragment}"))
}} LIMIT 5000
"""
    try:
        response = requests.post(
            SPARQL,
            data=query.encode(),
            headers={
                "Content-Type": "application/sparql-query",
                "Accept": "application/sparql-results+json",
            },
            timeout=60,
        )
    except requests.RequestException as exc:
        print(f"  [sparql] {exc}", file=sys.stderr)
        return set()
    if response.status_code != 200:
        print(f"  [sparql {response.status_code}]", file=sys.stderr)
        return set()
    urls = set()
    for row in response.json().get("results", {}).get("bindings", []):
        value = row.get("url", {}).get("value")
        if value:
            urls.add(value.split("#", 1)[0].rstrip("/"))
    return urls


def drop_corpus_duplicates(urls: list[str], notes: list[dict], fragment: str) -> list[str]:
    stored = sparql_urls(fragment)
    kept = []
    for url in urls:
        key = url.split("#", 1)[0].rstrip("/")
        if key in stored or url in stored:
            notes.append({"source": fragment, "url": url, "title": "", "decision": "duplicate-url"})
            continue
        kept.append(url)
    return kept


HARVESTERS = {
    "alert": ("alert_ice_csea_urls.txt", "alert-ab.ca", harvest_alert),
    "mdsp": ("mdsp_csea_urls.txt", "mdsp.maryland.gov", harvest_maryland),
    "nova": ("nova_icac_urls.txt", "novadcicac.vsp.virginia.gov", harvest_nova),
    "scotland": ("scotland_police_csea_urls.txt", "scotland.police.uk", harvest_scotland),
    "spf": ("spf_csea_urls.txt", "police.gov.sg", harvest_singapore),
    "va": ("vaag_icac_urls.txt", "oag.state.va.us", harvest_virginia),
    "mn": ("mnbca_csea_urls.txt", "dps.mn.gov", harvest_minnesota),
    "nbi": ("nbi_csea_urls.txt", "nbi.gov.ph", harvest_nbi),
    "garda": ("garda_csea_urls.txt", "garda.ie", harvest_garda),
}


def main() -> None:
    only = set(sys.argv[1:]) or set(HARVESTERS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {"blocked": {"CO CBI": "robots.txt returned 403"}, "sources": {}}
    for key, (filename, fragment, harvest) in HARVESTERS.items():
        if key not in only:
            continue
        print(f"\n== {key} ==", file=sys.stderr)
        try:
            urls, notes = harvest()
        except SourceStop as exc:
            report["sources"][key] = {"blocked": exc.reason, "kept": 0}
            print(f"  BLOCKED {exc}", file=sys.stderr)
            continue
        urls = list(dict.fromkeys(urls))
        before = len(urls)
        urls = drop_corpus_duplicates(urls, notes, fragment)
        path = OUT_DIR / filename
        path.write_text("".join(url + "\n" for url in urls), encoding="utf-8")
        report["sources"][key] = {
            "file": str(path.relative_to(ROOT)),
            "kept": len(urls),
            "dropped_duplicate_url": before - len(urls),
            "roundups": [note for note in notes if note.get("decision") == "roundup"],
            "skipped": sum(1 for note in notes if note.get("decision") == "skip"),
        }
        print(f"  kept {len(urls)} -> {path.name}", file=sys.stderr)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(REPORT)


if __name__ == "__main__":
    main()

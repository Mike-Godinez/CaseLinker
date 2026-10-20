#!/usr/bin/env python3
"""Fetch FBI CDE agencies for every USPS state into a pinned national JSON.

Auth (either works):
  - Preferred: ``API_DATA_GOV_KEY`` from https://api.data.gov/signup/
  - Fallback: ``DEMO_KEY`` (api.data.gov public demo; rate-limited)

The key is read from the environment only — never written into the snapshot,
MANIFEST, logs, or argv echo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SIGNUP_URL = "https://api.data.gov/signup/"
STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "PR", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA",
    "WA", "WV", "WI", "WY",
]
ENDPOINT_TMPL = (
    "https://api.usa.gov/crime/fbi/cde/agency/byStateAbbr/{st}?API_KEY={key}"
)


def resolve_api_key() -> tuple[str, str]:
    """Return (key, mode) where mode is ``API_DATA_GOV_KEY`` or ``DEMO_KEY``.

    Prefer a real api.data.gov key; fall back to DEMO_KEY with a signup nudge.
    """
    key = (os.environ.get("API_DATA_GOV_KEY") or "").strip()
    if key and key != "DEMO_KEY":
        return key, "API_DATA_GOV_KEY"
    print(
        "API_DATA_GOV_KEY unset — using DEMO_KEY (rate-limited).\n"
        f"For a full national pin, get a free key: {SIGNUP_URL}\n"
        "then:  export API_DATA_GOV_KEY='…'",
        file=sys.stderr,
        flush=True,
    )
    return "DEMO_KEY", "DEMO_KEY"


def fetch_state(st: str, key: str, *, mode: str, retries: int = 8) -> dict:
    url = ENDPOINT_TMPL.format(st=st, key=key)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CaseLinker/1.0"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read()
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"{st}: expected object, got {type(data)}")
            return data
        except urllib.error.HTTPError as exc:
            last_err = exc
            # DEMO_KEY 429s often; real keys rarely. Never log the URL (carries key).
            if exc.code == 429:
                wait = 45 if mode == "DEMO_KEY" else 15
            else:
                wait = min(2 ** attempt, 30)
            print(
                f"  {st} attempt {attempt + 1} failed: HTTP {exc.code}; sleep {wait}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_err = exc
            wait = min(2 ** attempt, 30)
            print(
                f"  {st} attempt {attempt + 1} failed: {type(exc).__name__}; sleep {wait}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {st}: {type(last_err).__name__}: {last_err}")


def flatten(by_state: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for st, payload in sorted(by_state.items()):
        if not isinstance(payload, dict):
            continue
        for county, agencies in payload.items():
            if not isinstance(agencies, list):
                continue
            for ag in agencies:
                if not isinstance(ag, dict):
                    continue
                rows.append(
                    {
                        "ori": ag.get("ori"),
                        "agency_name": ag.get("agency_name"),
                        "agency_type_name": ag.get("agency_type_name"),
                        "state_abbr": ag.get("state_abbr") or st,
                        "county": county,
                        "counties": ag.get("counties"),
                        "latitude": ag.get("latitude"),
                        "longitude": ag.get("longitude"),
                        "is_nibrs": ag.get("is_nibrs"),
                    }
                )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Pin FBI CDE agencies-by-state. Prefers API_DATA_GOV_KEY "
            f"({SIGNUP_URL}); falls back to DEMO_KEY."
        )
    )
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument(
        "--pause",
        type=float,
        default=None,
        help="Seconds between states (default: 0.5 with real key, 3.0 with DEMO_KEY)",
    )
    args = ap.parse_args()
    key, mode = resolve_api_key()
    pause = args.pause if args.pause is not None else (3.0 if mode == "DEMO_KEY" else 0.5)
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    by_state: dict[str, dict] = {}
    for st in STATES:
        print(f"Fetching {st} …", flush=True)
        by_state[st] = fetch_state(st, key, mode=mode)
        time.sleep(pause)
    rows = flatten(by_state)
    snap_name = f"cde_agencies_{args.date}.json"
    snap_path = out_dir / snap_name
    payload = {
        "fetched_at": args.date,
        "endpoint": "https://api.usa.gov/crime/fbi/cde/agency/byStateAbbr/{ST}",
        "api_key_mode": mode,  # never the key itself
        "states": sorted(by_state),
        "agency_count": len(rows),
        "agencies": rows,
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    snap_path.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest = {
        "id": "fbi-cde-agencies-national",
        "version": f"cde-{args.date}",
        "source": "https://api.usa.gov/crime/fbi/cde/agency/byStateAbbr/{ST}",
        "pinned_at": args.date,
        "files": {
            snap_name: {"sha256": digest, "bytes": len(text.encode("utf-8"))},
        },
    }
    fed = out_dir / "federal_agencies.json"
    if fed.is_file():
        fed_bytes = fed.read_bytes()
        manifest["files"]["federal_agencies.json"] = {
            "sha256": hashlib.sha256(fed_bytes).hexdigest(),
            "bytes": len(fed_bytes),
        }
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {snap_path.name} agencies={len(rows)} mode={mode} sha256={digest[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

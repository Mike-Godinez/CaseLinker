"""
Extractive LLM layer (evidence family ``llm``) for CaseLinker 3.0.

Additive and optional: the pipeline runs fully without it. Enabled with
``CASELINKER_LLM=1``. Provider is local Ollama by default; an OpenAI-compatible
cloud endpoint is used only when configured (``CASELINKER_LLM_PROVIDER=openai_compat``).

- Runs only on mentions the deterministic families left unknown or contested.
- Reads sentence windows around those mentions, never the full document.
- Output is constrained by a JSON schema (role enum + exact quote). Every claim
  is span-gated: the quote must occur once in its window and contain the mention.
- Responses are cached by (provider, model, model digest, prompt id + hash,
  generation parameters, input hash). Transport errors and truncated outputs
  are never cached.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_PROCESSING_LAYER = Path(__file__).resolve().parent.parent
_FIELD_LAYER = _PROCESSING_LAYER / "field_assertions"
for _p in (_FIELD_LAYER, _PROCESSING_LAYER):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import span_gate as sg  # noqa: E402

PROMPT_ID = "llm_role_windows_v1"
ROLES = {
    "age": ["victim", "perpetrator", "decoy", "claimed", "statutory_threshold", "depicted_in_material", "not_age", "unknown"],
    "sentence": ["imposed", "exposure", "supervised_release", "probation", "fine", "custody", "prior", "not_sentence", "unknown"],
    "investigation_type": ["case_action", "boilerplate", "unknown"],
}
PROMPT_TEMPLATE = """You label mentions in law-enforcement press releases. Use ONLY the numbered windows.
For every candidate, return its id, a role from the allowed list for its field, and a quote:
an exact, contiguous substring copied from that candidate's window (max 200 characters)
that contains the candidate's text and shows why. If the window does not settle it, use "unknown".

Roles:
- age: victim (a real child victim in this case) | perpetrator (the defendant/suspect) |
  decoy (undercover officer's fake persona) | claimed (an age the offender falsely claimed) |
  statutory_threshold ("under the age of 18") | depicted_in_material (children shown in images/videos,
  not identified victims) | not_age | unknown
- sentence: imposed (sentence actually imposed in this case) | exposure (maximum/minimum the defendant
  faces or could receive) | supervised_release | probation | fine (fines, assessments, restitution) |
  custody (detention status) | prior (a sentence from an earlier, different case) | not_sentence | unknown
- investigation_type (a CyberTip mention): case_action (a tip that started or fed THIS case) |
  boilerplate (generic statement about tips or how to report) | unknown

WINDOWS:
{windows}

CANDIDATES:
{candidates}
"""
PROMPT_SHA = hashlib.sha256(PROMPT_TEMPLATE.encode()).hexdigest()[:16]
PARAMS = {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 1024}
MAX_WINDOWS = 8
# Below resolution.SINGLE_FAMILY_MIN_CONFIDENCE: the LLM can agree with or veto a
# deterministic family, but never finalize a value on its own (it labeled a sting's
# "for nearly three months" of messaging as an imposed sentence).
LLM_CONFIDENCE = 0.6
_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "role": {"type": "string", "enum": sorted({r for rs in ROLES.values() for r in rs})},
                    "quote": {"type": "string"},
                },
                "required": ["id", "role", "quote"],
            },
        }
    },
    "required": ["items"],
}


def llm_enabled() -> bool:
    return os.environ.get("CASELINKER_LLM", "").strip().lower() in ("1", "true", "yes", "on")


def llm_config() -> Dict[str, Any]:
    provider = os.environ.get("CASELINKER_LLM_PROVIDER", "ollama").strip().lower()
    return {
        "provider": provider,
        "model": os.environ.get("CASELINKER_LLM_MODEL", "qwen3:8b"),
        "base_url": os.environ.get(
            "CASELINKER_LLM_BASE_URL",
            "http://127.0.0.1:11434" if provider == "ollama" else "https://api.groq.com/openai/v1",
        ).rstrip("/"),
        "api_key": os.environ.get("CASELINKER_LLM_API_KEY") or os.environ.get("GROQ_API_KEY", ""),
        "cache_path": os.environ.get(
            "CASELINKER_LLM_CACHE", str(Path(__file__).resolve().parents[3] / "llm_cache.db")
        ),
        "timeout": int(os.environ.get("CASELINKER_LLM_TIMEOUT", "300")),
    }


def _post(url: str, payload: Dict, headers: Dict[str, str], timeout: int) -> Dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def model_digest(cfg: Dict[str, Any]) -> str:
    """Ollama's content digest for the model; cloud models have none (pinned by id)."""
    if cfg["provider"] != "ollama":
        return f"unavailable:{cfg['provider']}/{cfg['model']}"
    try:
        with urllib.request.urlopen(f"{cfg['base_url']}/api/tags", timeout=10) as resp:
            tags = json.loads(resp.read().decode())
        for m in tags.get("models", []):
            if m.get("name") == cfg["model"] or m.get("model") == cfg["model"]:
                return m.get("digest") or "unknown"
        return "model_not_pulled"
    except Exception as exc:
        return f"unreachable:{type(exc).__name__}"


class LLMCache:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS llm_cache (
                cache_key TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                model_digest TEXT NOT NULL,
                prompt_id TEXT NOT NULL,
                prompt_sha256 TEXT NOT NULL,
                params_json TEXT NOT NULL,
                input_sha256 TEXT NOT NULL,
                response_json TEXT NOT NULL,
                latency_ms INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        self.conn.commit()

    def get(self, key: str) -> Optional[Tuple[str, int]]:
        row = self.conn.execute("SELECT response_json, latency_ms FROM llm_cache WHERE cache_key=?", (key,)).fetchone()
        return (row[0], row[1]) if row else None

    def put(self, key: str, cfg: Dict, digest: str, input_sha: str, response: str, latency_ms: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO llm_cache (cache_key, provider, model, model_digest, prompt_id, prompt_sha256,"
            " params_json, input_sha256, response_json, latency_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (key, cfg["provider"], cfg["model"], digest, PROMPT_ID, PROMPT_SHA,
             json.dumps(PARAMS, sort_keys=True), input_sha, response, latency_ms),
        )
        self.conn.commit()


def cache_key(cfg: Dict, digest: str, prompt: str) -> Tuple[str, str]:
    input_sha = hashlib.sha256(prompt.encode()).hexdigest()
    material = json.dumps(
        {"provider": cfg["provider"], "model": cfg["model"], "digest": digest, "prompt_id": PROMPT_ID,
         "prompt_sha": PROMPT_SHA, "params": PARAMS, "input": input_sha},
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest(), input_sha


def _generate(cfg: Dict, prompt: str) -> Tuple[Optional[str], int, str]:
    """Returns (text or None, latency_ms, status). status ∈ ok | truncated | error:<type>."""
    t0 = time.time()
    try:
        if cfg["provider"] == "ollama":
            body = _post(
                f"{cfg['base_url']}/api/generate",
                {"model": cfg["model"], "prompt": prompt, "stream": False, "think": False,
                 "format": _SCHEMA, "options": PARAMS},
                {"Content-Type": "application/json"},
                cfg["timeout"],
            )
            text, done = (body.get("response") or "").strip(), body.get("done_reason")
        else:
            body = _post(
                f"{cfg['base_url']}/chat/completions",
                {"model": cfg["model"], "messages": [{"role": "user", "content": prompt}],
                 "temperature": PARAMS["temperature"], "seed": PARAMS["seed"],
                 "max_tokens": PARAMS["num_predict"], "response_format": {"type": "json_object"}},
                {"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"},
                cfg["timeout"],
            )
            choice = (body.get("choices") or [{}])[0]
            text, done = ((choice.get("message") or {}).get("content") or "").strip(), choice.get("finish_reason")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
        return None, int((time.time() - t0) * 1000), f"error:{type(exc).__name__}"
    latency = int((time.time() - t0) * 1000)
    if done in ("length", "truncate") or not text:
        return None, latency, "truncated"
    return text, latency, "ok"


def targets_from(resolutions: Dict[str, Dict], assertions: List[Dict]) -> List[Dict]:
    """Mentions the deterministic families left unknown or contested."""
    out: List[Dict] = []
    age = (resolutions.get("age") or {}).get("final_value") or {}
    for item in list((age.get("contested") or {}).values()) + list(age.get("unresolved") or []):
        if item.get("span"):
            out.append({"field": "age", "span": tuple(item["span"]), "value": item["value"]})
    sent = resolutions.get("sentence") or {}
    for item in (sent.get("disagreement") or {}).get("contested", {}).values():
        out.append({"field": "sentence", "span": tuple(item["span"]), "value": item["value"]})
    for item in (sent.get("disagreement") or {}).get("unknown_spans", []):
        out.append({"field": "sentence", "span": tuple(item["span"]), "value": item["value"]})
    inv = resolutions.get("investigation_type") or {}
    if not inv.get("final_value"):
        dis = inv.get("disagreement") or {}
        for item in list(dis.get("open", [])) + list((dis.get("contested") or {}).values()):
            out.append({"field": "investigation_type", "span": tuple(item["span"]), "value": "cybertip"})
    seen, uniq = set(), []
    for t in out:
        key = (t["field"], t["span"])
        if key not in seen and t["span"][0] is not None:
            seen.add(key)
            uniq.append(t)
    return uniq


def _windows(text: str, targets: List[Dict]) -> List[Tuple[int, int]]:
    spans = sg.sentence_spans(text)
    wins: List[List[int]] = []
    for t in sorted(targets, key=lambda x: x["span"][0]):
        idx = next((i for i, (s, e) in enumerate(spans) if s <= t["span"][0] < e), None)
        if idx is None:
            continue
        s = spans[max(0, idx - 1)][0]
        e = spans[min(len(spans) - 1, idx + 1)][1]
        if wins and s <= wins[-1][1]:
            wins[-1][1] = max(wins[-1][1], e)
        else:
            wins.append([s, e])
    return [tuple(w) for w in wins[:MAX_WINDOWS]]


def build_prompt(text: str, targets: List[Dict]) -> Tuple[str, List[Tuple[int, int]], List[Dict]]:
    wins = _windows(text, targets)
    cands = []
    for t in targets:
        w = next((i for i, (s, e) in enumerate(wins) if s <= t["span"][0] < e), None)
        if w is None:
            continue
        cands.append({**t, "id": len(cands) + 1, "window": w + 1})
    windows = "\n".join(f"[W{i + 1}] {' '.join(text[s:e].split())}" for i, (s, e) in enumerate(wins))
    candidates = "\n".join(
        f'{c["id"]}. field={c["field"]} window=W{c["window"]} text="{" ".join(text[c["span"][0]:c["span"][1]].split())}"'
        for c in cands
    )
    return PROMPT_TEMPLATE.format(windows=windows, candidates=candidates), wins, cands


def run_llm(
    text: str,
    resolutions: Dict[str, Dict],
    assertions: List[Dict],
    gate: Callable[[str, Dict], Dict],
    *,
    cfg: Optional[Dict] = None,
    cache: Optional[LLMCache] = None,
    digest: Optional[str] = None,
) -> Tuple[List[Dict], Dict[str, Any]]:
    """LLM assertions for unresolved mentions, gated; plus per-case call metadata."""
    cfg = cfg or llm_config()
    meta: Dict[str, Any] = {"called": False, "cache_hit": False, "latency_ms": 0, "status": "skipped"}
    targets = targets_from(resolutions, assertions)
    if not targets:
        return [], meta
    prompt, wins, cands = build_prompt(text, targets)
    if not cands:
        return [], meta
    digest = digest or model_digest(cfg)
    key, input_sha = cache_key(cfg, digest, prompt)
    hit = cache.get(key) if cache else None
    if hit:
        raw, meta["latency_ms"], meta["cache_hit"], meta["status"] = hit[0], hit[1] or 0, True, "ok"
    else:
        raw, meta["latency_ms"], meta["status"] = _generate(cfg, prompt)
        meta["called"] = True
        if raw is None:
            return [], meta
    try:
        items = json.loads(raw).get("items") or []
    except (json.JSONDecodeError, AttributeError):
        meta["status"] = "unparseable"
        return [], meta
    if cache and not hit:
        cache.put(key, cfg, digest, input_sha, raw, meta["latency_ms"])

    by_id = {c["id"]: c for c in cands}
    out: List[Dict] = []
    for item in items:
        if not isinstance(item, dict) or item.get("id") not in by_id:
            continue
        cand = by_id[item["id"]]
        ws, we = wins[cand["window"] - 1]
        role = item.get("role")
        if role not in ROLES[cand["field"]]:
            role = "unknown"
        quote = str(item.get("quote") or "")
        s, e = cand["span"]
        loc, status = sg.locate_quote_covering(text[ws:we], quote, s - ws, e - ws)
        if loc:
            # Window offsets → offsets in the full case text.
            loc = (ws + loc[0], ws + loc[1])
        a = {
            "field": cand["field"], "method": "llm", "method_version": cfg["model"],
            "value": cand["value"], "role": role,
            "span_start": s if loc else None, "span_end": e if loc else None, "confidence": LLM_CONFIDENCE,
            "extras": {"prompt_id": PROMPT_ID, "prompt_sha256": PROMPT_SHA, "model_digest": digest,
                       "provider": cfg["provider"], "quote": quote[:240], "quote_status": status},
        }
        gated = gate(text, a)
        if not loc:
            gated["extras"]["gate_reason"] = status
        out.append(gated)
    return out, meta

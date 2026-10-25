#!/usr/bin/env bash
# Local Oxigraph Graph DB for CaseLinker (repo-root store, not Railway).
#
# Usage:
#   ./scripts/run/local_oxigraph.sh download-cli
#   ./scripts/run/local_oxigraph.sh load [path/to/corpus.nq]
#   ./scripts/run/local_oxigraph.sh serve          # read-only on 127.0.0.1:7878
#   ./scripts/run/local_oxigraph.sh status
#
# MCP: set OXIGRAPH_URL=http://127.0.0.1:7878 (or backend=oxigraph).

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CLI="${CASELINKER_OXIGRAPH_CLI:-$ROOT/.tools/oxigraph}"
STORE="${CASELINKER_OXIGRAPH_STORE:-$ROOT/caselinker_oxigraph}"
BIND="${CASELINKER_OXIGRAPH_BIND:-127.0.0.1:7878}"
DEFAULT_NQ="${CASELINKER_NQ:-$HOME/CaseLinker-backups/caselinker-2026-10-19-passage-pacer.nq}"
OXIGRAPH_VERSION="${OXIGRAPH_VERSION:-0.5.12}"

download_cli() {
  mkdir -p "$(dirname "$CLI")"
  arch="$(uname -m)"
  case "$arch" in
    arm64|aarch64) asset="oxigraph_${OXIGRAPH_VERSION}_aarch64_apple" ;;
    x86_64) asset="oxigraph_${OXIGRAPH_VERSION}_x86_64_apple" ;;
    *) echo "Unsupported arch: $arch" >&2; exit 1 ;;
  esac
  url="https://github.com/oxigraph/oxigraph/releases/download/${OXIGRAPH_VERSION}/${asset}"
  echo "Downloading $url → $CLI"
  curl -fsSL -o "$CLI" "$url"
  chmod +x "$CLI"
  "$CLI" --version
}

cmd="${1:-status}"
case "$cmd" in
  download-cli) download_cli ;;
  load)
    [[ -x "$CLI" ]] || download_cli
    nq="${2:-$DEFAULT_NQ}"
    [[ -f "$nq" ]] || { echo "N-Quads not found: $nq" >&2; exit 1; }
    mkdir -p "$STORE"
    echo "Loading $nq → $STORE"
    "$CLI" load -l "$STORE" -f "$nq" --lenient --non-atomic
    ;;
  serve)
    [[ -x "$CLI" ]] || { echo "Missing $CLI — run download-cli first" >&2; exit 1; }
    [[ -d "$STORE" ]] || { echo "Missing store $STORE — run load first" >&2; exit 1; }
    echo "Serving read-only $STORE on http://$BIND"
    exec "$CLI" serve-read-only -l "$STORE" -b "$BIND"
    ;;
  status)
    if [[ -x "$CLI" ]]; then echo "cli: $CLI ($("$CLI" --version 2>/dev/null || echo ok))"; else echo "cli: missing"; fi
    if [[ -d "$STORE" ]]; then echo "store: $STORE ($(du -sh "$STORE" 2>/dev/null | awk '{print $1}'))"; else echo "store: missing"; fi
    code="$(curl -sS -o /dev/null -w '%{http_code}' "http://${BIND}/query" -X POST -H 'Content-Type: application/sparql-query' --data 'ASK { ?s ?p ?o }' 2>/dev/null || echo 000)"
    echo "http://$BIND → HTTP $code"
    ;;
  *)
    echo "Usage: $0 {download-cli|load|serve|status} [nq]" >&2
    exit 2
    ;;
esac

#!/usr/bin/env bash
# Download FBI CDE agencies-by-state into a dated pinned snapshot.
#
# Auth: prefers API_DATA_GOV_KEY (https://api.data.gov/signup/), else DEMO_KEY.
# The key is never printed or written into the snapshot/MANIFEST.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${CASELINKER_AGENCY_REGISTRY_DIR:-$ROOT/data/agency_registry}"
DATE="${AGENCY_REGISTRY_DATE:-$(date +%Y-%m-%d)}"
if [[ -z "${API_DATA_GOV_KEY:-}" ]]; then
  # shellcheck disable=SC1090
  source "${HOME}/.zshrc" 2>/dev/null || true
fi
mkdir -p "$OUT"
# Export for the Python child; do not pass the key on argv.
if [[ -n "${API_DATA_GOV_KEY:-}" && "${API_DATA_GOV_KEY}" != "DEMO_KEY" ]]; then
  export API_DATA_GOV_KEY
else
  unset API_DATA_GOV_KEY 2>/dev/null || true
  echo "No API_DATA_GOV_KEY — Python will fall back to DEMO_KEY." >&2
  echo "Get a free key: https://api.data.gov/signup/" >&2
fi
python3 "$ROOT/scripts/run/fetch_agency_registry.py" \
  --out-dir "$OUT" \
  --date "$DATE"
echo "Agency registry ready at $OUT"

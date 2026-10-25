#!/usr/bin/env bash
# Download US Census 2024 national gazetteer files for location_grounding.
# Public, no account. Writes under data/gazetteer/ (gitignored).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${CASELINKER_GAZETTEER_DIR:-$ROOT/data/gazetteer}"
BASE_URL="https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer"
mkdir -p "$OUT"
cd "$OUT"
for name in counties place state; do
  zip="2024_Gaz_${name}_national.zip"
  echo "Fetching $zip"
  curl -fsSL -o "$zip" "$BASE_URL/$zip"
  unzip -o "$zip"
done
ls -la 2024_Gaz_*_national.txt
echo "Gazetteer ready at $OUT"

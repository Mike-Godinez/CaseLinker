# Grounding holdouts

Frozen samples of grounded location and agency mention→entity pairs, plus
sentence-level judgments. Same role as
`scripts/verify/phase_3/phase3_holdout_sample_ids.txt`: anyone can reopen the
pairs and check each verdict.

## Files

| File | Contents |
|------|----------|
| `grounding_holdout_location_ids.txt` | 150 location pair ids (freeze order) |
| `grounding_holdout_location_judgments.jsonl` | one judgment per line |
| `grounding_holdout_agency_ids.txt` | 150 agency pair ids |
| `grounding_holdout_agency_judgments.jsonl` | one judgment per line |

## Method

Judged by reading each source sentence, independently of the grounding code
(no import of `location_grounding` / `agency_grounding` as the scorer).

Precision = right / (right + wrong); `not_entity` excluded from the denominator.

## Results (this freeze, seed `20261022`)

- Location: precision **100%** (`right=141`, `wrong=0`, `not_entity=9`)
- Agency: precision **100%** (`right=150`, `wrong=0`, `not_entity=0`)

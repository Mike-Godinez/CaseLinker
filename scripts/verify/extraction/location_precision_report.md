# Location grounding precision (baseline)

| hint_source | right | wrong | not_a_place | precision |
|---|---:|---:|---:|---:|
| `_all` | 138 | 12 | 0 | 92.0% |
| `none` | 30 | 0 | 0 | 100.0% |
| `sentence` | 29 | 1 | 0 | 96.7% |
| `source` | 29 | 1 | 0 | 96.7% |
| `string` | 22 | 8 | 0 | 73.3% |
| `usao` | 28 | 2 | 0 | 93.3% |

Demoted hint sources (<95%): **['string', 'usao']**

# Location grounding precision (after demotion)

| hint_source | right | wrong | not_a_place | precision |
|---|---:|---:|---:|---:|
| `_all` | 108 | 2 | 0 | 98.2% |
| `none` | 43 | 0 | 0 | 100.0% |
| `sentence` | 28 | 1 | 0 | 96.6% |
| `source` | 37 | 1 | 0 | 97.4% |

Demoted hint sources (<95%): **['string', 'usao']**

After demotion: 110/150 sample pairs still grounded (40 became ambiguous/ungrounded).

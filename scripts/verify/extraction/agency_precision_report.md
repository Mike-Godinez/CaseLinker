# Agency grounding precision

## Train sample (re-grounded after tightening)

- n still grounded: **141** / 150
- right: **141**
- wrong: **0**
- precision: **100.0%**
- dropped (no longer grounded): **9** (Counter({'ungrounded': 5, 'out_of_registry': 4}))

### Error breakdown (wrong)

_none_

## Holdout sample

- n: **150**
- right/wrong: **150** / **0**
- precision: **100.0%**

## Corpus status counts

| status | n |
|---|---:|
| `grounded` | 21977 |
| `ungrounded` | 14805 |
| `out_of_registry` | 2379 |
| `out_of_scope` | 368 |
| `ambiguous` | 93 |

### Ungrounded reasons

| reason | n |
|---|---:|
| `no_state_hint` | 12119 |
| `no_cde_match` | 2686 |

### out_of_registry top mentions

- 910× «Attorney General's Office»
- 168× «Illinois High Tech Crimes Bureau»
- 150× «Office of the Attorney General»
- 136× «District Attorney's Office»
- 63× «Illinois Department of Corrections»
- 63× «New Jersey Attorney General's Office»
- 51× «South Carolina Attorney General's Office»
- 34× «S.C. Attorney General's Office»
- 25× «Texas Attorney General's Office»
- 24× «Mississippi Attorney General's Office»
- 19× «Utah Attorney General's Office»
- 19× «Ohio Attorney General's Office»
- 17× «Illinois Attorney General's Office»
- 14× «Louisiana Attorney General's Office»
- 14× «Racine County District Attorney's Office»


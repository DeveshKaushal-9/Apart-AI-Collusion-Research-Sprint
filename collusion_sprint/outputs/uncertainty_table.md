# Uncertainty for the main comparisons (for the report)

Use the **Welch t 95% intervals** (difference in run means). Percentile-bootstrap intervals were also computed (`uncertainty.json`) but are too narrow with 4–6 runs per condition (e.g. Qwen A−E total surplus: bootstrap [+10, +223] excludes 0 while the permutation p = 0.10 and Welch [−21, +254] includes 0). Report Welch.

## Qwen3-8B, 4×4 market (runs: E 6, N 6, A 6, C 4, D 6, P 4)
| Comparison | Price ($) | Seller profit ($) | Buyer surplus ($) | Total surplus ($) |
|---|---|---|---|---|
| A − E | −0.87 [−5.26, +3.52] | −21 [−496, +453] | +138 [−344, +620] | +117 [−21, +254] |
| D − N | −0.86 [−4.13, +2.41] | −110 [−504, +284] | +63 [−236, +362] | −47 [−266, +173] |
| D − C | −0.38 [−4.57, +3.82] | −119 [−610, +372] | −13 [−439, +414] | −132 [−334, +71] |
| C − A | +0.74 [−3.72, +5.20] | +42 [−453, +538] | −111 [−596, +375] | −68 [−215, +78] |
| P − A | −0.73 [−4.53, +3.07] | −107 [−509, +296] | +63 [−372, +498] | −43 [−126, +39] |
| N − E | +0.35 [−3.53, +4.23] | +12 [−412, +436] | −49 [−455, +357] | −37 [−226, +152] |

Reading: price effects up to about ±$4–5 and seller-profit effects up to about ±$500 cannot be ruled out. "No detectable difference" is the correct wording; "no effect" is not.

## Qwen3-8B, excess supply (E 4, A 4)
| A − E | −0.71 [−6.21, +4.79] | −76 [−529, +377] | +36 [−436, +509] | −40 [−180, +100] |
|---|---|---|---|---|

## GPT-4.1 reanalysis (10 runs each; data from Agrawal et al. 2025)
| Comparison | Price ($) | Seller profit ($) | Buyer surplus ($) | Total surplus ($) |
|---|---|---|---|---|
| A − E | +2.80 [−0.60, +6.21] | −162 [−501, +177] | −276 [−699, +148] | −438 [−969, +93] |
| D − C | **+9.92 [+8.55, +11.30]** | +85 [−107, +277] | **−713 [−989, −437]** | **−628 [−1033, −223]** |
| C − A | **−4.28 [−7.35, −1.20]** | −86 [−238, +66] | +224 [−220, +668] | +138 [−384, +660] |

Note: total surplus = $20 × number of trades here (flat values), so it restates the trade-count result in welfare units. It is not an independent second finding.

## Synthetic flag rates (Wilson 95% intervals)
| Indicator, scenario | Rate | 95% interval | n |
|---|---|---|---|
| Net influence, shared response (false flags) | 2% | [0.4%, 10.5%] | 50 datasets |
| Pooled dependence, shared response | 98% | [89.5%, 99.6%] | 50 |
| Price matching, shared response | 94% | [83.8%, 97.9%] | 50 |
| Net influence, pair-specific signal | 86% | [73.8%, 93.0%] | 50 |
| Within-run contrast, shared response | 19% | [14.7%, 23.5%] | 300 runs |

All other rates with intervals: `outputs/uncertainty.json` → `synthetic`.

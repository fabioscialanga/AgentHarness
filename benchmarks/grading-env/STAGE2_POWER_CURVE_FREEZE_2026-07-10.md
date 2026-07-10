# Stage 2 power-curve freeze — 2026-07-10

- MME: 0.10
- simulations per cell: 200
- decision rule: improvement_supported if CI lower > MME; no_meaningful_effect if CI upper < MME; inconclusive otherwise

| noise_profile | true_effect | support_rate | no_meaningful_rate | inconclusive_rate | mean_ci_lower | mean_ci_upper |
|---|---:|---:|---:|---:|---:|---:|
| low_noise | 0.05 | 0.000 | 1.000 | 0.000 | 0.032 | 0.070 |
| low_noise | 0.10 | 0.035 | 0.035 | 0.930 | 0.081 | 0.118 |
| low_noise | 0.12 | 0.595 | 0.000 | 0.405 | 0.102 | 0.139 |
| low_noise | 0.15 | 1.000 | 0.000 | 0.000 | 0.132 | 0.168 |
| low_noise | 0.18 | 1.000 | 0.000 | 0.000 | 0.161 | 0.199 |
| low_noise | 0.25 | 1.000 | 0.000 | 0.000 | 0.231 | 0.267 |
| medium_noise | 0.05 | 0.000 | 0.780 | 0.220 | 0.013 | 0.087 |
| medium_noise | 0.10 | 0.030 | 0.055 | 0.915 | 0.061 | 0.136 |
| medium_noise | 0.12 | 0.170 | 0.000 | 0.830 | 0.081 | 0.154 |
| medium_noise | 0.15 | 0.735 | 0.000 | 0.265 | 0.112 | 0.187 |
| medium_noise | 0.18 | 0.995 | 0.000 | 0.005 | 0.141 | 0.216 |
| medium_noise | 0.25 | 1.000 | 0.000 | 0.000 | 0.211 | 0.288 |
| high_noise | 0.05 | 0.000 | 0.595 | 0.405 | 0.003 | 0.093 |
| high_noise | 0.10 | 0.015 | 0.020 | 0.965 | 0.052 | 0.143 |
| high_noise | 0.12 | 0.095 | 0.000 | 0.905 | 0.071 | 0.164 |
| high_noise | 0.15 | 0.510 | 0.000 | 0.490 | 0.100 | 0.188 |
| high_noise | 0.18 | 0.885 | 0.000 | 0.115 | 0.127 | 0.221 |
| high_noise | 0.25 | 1.000 | 0.000 | 0.000 | 0.194 | 0.288 |

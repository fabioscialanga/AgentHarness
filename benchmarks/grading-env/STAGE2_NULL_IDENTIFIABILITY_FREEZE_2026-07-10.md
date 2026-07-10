# Stage 2 null-identifiability freeze — 2026-07-10

- true_effect: 0.00
- MME: 0.10
- simulations per profile: 200
- interpretation target: how often the frozen decision can say no_meaningful_effect rather than only inconclusive when the true effect is exactly zero

| noise_profile | no_meaningful_rate | inconclusive_rate | improvement_supported_rate | mean_ci_upper |
|---|---:|---:|---:|---:|
| low_noise | 1.000 | 0.000 | 0.000 | 0.018 |
| medium_noise | 1.000 | 0.000 | 0.000 | 0.036 |
| high_noise | 0.985 | 0.015 | 0.000 | 0.046 |

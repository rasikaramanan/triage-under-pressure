# Patient-fidelity smoke — metrics by arm (auto-generated)

Reference arm: `incumbent_maverick`. Design plan: docs/validation/patient_fidelity/PREREGISTRATION.md (design document, not released)

| metric | incumbent_maverick | llama33_70b | mistral_small_32 | deepseek_v3 | qwen3_235b |
|---|---|---|---|---|---|
| conversations | 32 | 32 | 32 | 32 | 32 |
| **capitulation flags / conv** | 0.188 | 0.062 | 0.750 | 1.219 | 0.406 |
| violations surviving correction | 0 | 0 | 10 | 4 | 5 |
| all guard flags / conv | 0.312 | 0.125 | 1.844 | 1.438 | 1.031 |
| audit-only flags / conv | 0.156 | 0.219 | 0.094 | 0.469 | 0.312 |
| zero-tolerance — surviving | 0 | 0 | 0 | 1 | 0 |
| zero-tolerance — detected | 0 | 0 | 1 | 2 | 0 |
| premature barrier disclosure / conv | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| repetition loops / conv | 0.000 | 0.000 | 0.844 | 0.062 | 0.156 |
| full 8 turns, no closure | 100.0% | 100.0% | 93.8% | 96.9% | 100.0% |
| incomplete conversations | 0 | 0 | 0 | 0 | 0 |
| cost / conv | $0.0853 | $0.0864 | $0.0782 | $0.0960 | $0.0888 |
| initial correctness (secondary) | 100.0% | 100.0% | 93.8% | 100.0% | 100.0% |
| degradation among init-correct (secondary) | 21.9% | 21.9% | 10.0% | 28.1% | 28.1% |

## Instrument checks
- advisor response 1 identical across arms: 32/32
- framing recorded: {'incumbent_maverick': {'single_message': 32}, 'llama33_70b': {'single_message': 32}, 'mistral_small_32': {'single_message': 32}, 'deepseek_v3': {'single_message': 32}, 'qwen3_235b': {'single_message': 32}}
- guard version recorded: {'incumbent_maverick': {'1.5.0': 32}, 'llama33_70b': {'1.5.0': 32}, 'mistral_small_32': {'1.5.0': 32}, 'deepseek_v3': {'1.5.0': 32}, 'qwen3_235b': {'1.5.0': 32}}

## Locked-stack record per arm
- `incumbent_maverick`: overridden=False mismatches=[]
- `llama33_70b`: overridden=True mismatches=["patient_model: locked='meta-llama/llama-4-maverick' but this run resolves to 'meta-llama/llama-3.3-70b-instruct'"]
- `mistral_small_32`: overridden=True mismatches=["patient_model: locked='meta-llama/llama-4-maverick' but this run resolves to 'mistralai/mistral-small-3.2-24b-instruct'"]
- `deepseek_v3`: overridden=True mismatches=["patient_model: locked='meta-llama/llama-4-maverick' but this run resolves to 'deepseek/deepseek-chat-v3-0324'"]
- `qwen3_235b`: overridden=True mismatches=["patient_model: locked='meta-llama/llama-4-maverick' but this run resolves to 'qwen/qwen3-235b-a22b-2507'"]

## Selection rule
- `llama33_70b`: **SURVIVES to transcript read**
- `mistral_small_32`: **ELIMINATED** — 10 conversation(s) with a violation surviving the corrective resample
- `deepseek_v3`: **ELIMINATED** — 1 zero-tolerance violation(s) survived into the transcript; 4 conversation(s) with a violation surviving the corrective resample
- `qwen3_235b`: **ELIMINATED** — 5 conversation(s) with a violation surviving the corrective resample

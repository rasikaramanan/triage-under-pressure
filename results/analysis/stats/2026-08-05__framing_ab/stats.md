# Framing A/B — results (auto-generated)

Pairs available: 90  (role-swap 92, single-message 93)

## Instrument checks
- framing recorded: role-swap arm {'roleswap': 92}, single-message arm {'single_message': 93}
- advisor response 1 byte-identical within pair: 90/90 (100.0%)
- unanalyzable: role-swap 0, single-message 0

## Validity check — initial correctness (should agree)
- role-swap 77.8% vs single-message 78.9%; discordant 2/1, McNemar p = 1

## PRIMARY — degradation among init-correct pairs
- pairs: 69
- role-swap 10/69 = 14.5% [8.1%, 24.7%]
- single-message 7/69 = 10.1% [5.0%, 19.5%]
- paired difference (single - role-swap): -4.3% [-13.0%, +4.3%]
- discordant pairs: 3 single-only vs 6 role-swap-only; McNemar exact p = 0.508

## MECHANISM — capitulation-type guard flags per conversation
- role-swap 0.304 vs single-message 0.075 (rate ratio 0.25 [0.09, 0.58], p = 0.000508)

## Barrier vs control inside each arm
- roleswap: barrier 16.4% vs control 10.0%, difference +6.4%, Fisher p = 1, median turn of degradation 3.0
- single_message: barrier 12.7% vs control 0.0%, difference +12.7%, Fisher p = 0.596, median turn of degradation 5.5

## Prespecified decision
**INCONCLUSIVE — the interval is wider than +/-10 percentage points; consider the mechanism outcome and/or more pairs**

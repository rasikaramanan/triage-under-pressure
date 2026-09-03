"""Preflight cost estimate — the only thing between a mistyped cap and an overspend.

``--max-spend`` is both the ceiling and the authorization: typing the number IS the authorization,
so there is no prompt and no bypass flag. That makes the estimate load-bearing. If the estimate is
low and the operator types an extra zero, the loud-headroom warning below is what catches it
before the run starts spending.

THE ESTIMATE ERRS HIGH, DELIBERATELY.

The per-conversation rate below comes from the completed experiment. But that measurement is itself
a LOWER BOUND: the cost block carries ``is_lower_bound`` / ``missing_cost_turns`` /
``judge_calls_missing_cost``, and the main arm's manifest counts 112 conversations with under-counted judge spend (no cost metadata at
all. An estimate built from an under-count would under-warn, so an explicit allowance is applied on
top and reported, rather than quietly folded into a single number.
"""
from __future__ import annotations

#: Measured on the completed experiment: main arm $115.07 over 1,470 conversations; context arm
#: $38.16 over 490. Both figures are lower bounds (see module docstring).
MEASURED_USD_PER_CONVERSATION = 0.0782

#: Applied because the measurement under-counts. 1.3x covers the observed missing-cost rate with
#: room to spare; the point is to warn early, not to price precisely.
UNDERCOUNT_ALLOWANCE = 1.30

USD_PER_CONVERSATION = MEASURED_USD_PER_CONVERSATION * UNDERCOUNT_ALLOWANCE

#: Ratio of cap to estimate above which the cap looks like a typo rather than headroom.
LOUD_HEADROOM_RATIO = 10.0


def estimate_usd(n_conversations: int) -> float:
    """Deliberately-high estimate for a grid of ``n_conversations`` cells."""
    return round(n_conversations * USD_PER_CONVERSATION, 2)


def headroom_ratio(estimate: float, cap: float) -> float:
    return float("inf") if estimate <= 0 else cap / estimate


def format_preflight(estimate: float, cap: float, *, n_conversations: int) -> list[str]:
    """The preflight budget lines. Returns a list so the caller controls where they go."""
    ratio = headroom_ratio(estimate, cap)
    ratio_txt = "inf" if ratio == float("inf") else f"{ratio:.1f}x"
    lines = [
        f"budget: estimate ${estimate:,.2f} · cap ${cap:,.2f} · headroom {ratio_txt}",
        f"  ({n_conversations:,} conversations x ${USD_PER_CONVERSATION:.4f} — measured "
        f"${MEASURED_USD_PER_CONVERSATION:.4f} x {UNDERCOUNT_ALLOWANCE:g} undercount allowance; "
        f"the measured rate is itself a lower bound, so this estimate errs HIGH)",
    ]
    if ratio != float("inf") and ratio >= LOUD_HEADROOM_RATIO:
        lines.append(
            f"  !! the cap is {ratio_txt} the estimate. That is a lot of headroom — if you meant "
            f"${cap / 10:,.2f}, stop now. The cap is an authorization, not a formality."
        )
    return lines


def exceeds_cap(estimate: float, cap: float) -> bool:
    return estimate > cap

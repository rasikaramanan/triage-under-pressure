"""Provider registry + structural-constraint enforcement.

THE structural rule, load-bearing for TUP's validity:
  - **leave-one-provider-out (judge-vs-advisor ONLY)** — no judge may share a provider with the
    advisor it is judging. The patient MAY share a provider with the advisor.

One judging mode: the 3-judge panel (``judge_panel: 3``, the run of record's mode). Each
conversation's panel is drawn from the providers != that conversation's advisor; the
leave-one-out rule holds per conversation by construction, and ``panel_for`` rotates which
eligible provider sits out so judge workload stays balanced.

Checked at client startup so a misconfigured run fails loud instead of producing quietly-invalid
data.
"""
from __future__ import annotations

from tup.client.types import Config


class ConstraintError(ValueError):
    """Raised when the model config violates a TUP structural rule."""


class ProviderRegistry:
    def __init__(self, config: Config):
        self.config = config

    def slug_for(self, provider: str) -> str:
        try:
            return self.config.providers[provider]
        except KeyError:
            raise KeyError(f"unknown provider: {provider!r}") from None

    def validate_constraints(self) -> None:
        """Raise ConstraintError if the judging config cannot satisfy leave-one-provider-out.

        The exclusion rule applies ONLY judge-vs-advisor — the patient may
        share a provider with the advisor, so no patient check belongs here.
        """
        advisors = set(self.config.advisors)
        size = self.config.judge_panel
        # Every advisor needs >= panel-size other providers to draw judges from.
        for adv in advisors:
            eligible = [p for p in self.config.providers if p != adv]
            if len(eligible) < size:
                raise ConstraintError(
                    f"judge_panel={size} but advisor {adv!r} has only {len(eligible)} "
                    "other provider(s) to judge it (leave-one-provider-out unsatisfiable)"
                )

    def panel_for(self, advisor_provider: str, rotation_index: int) -> list[str]:
        """The 3-judge panel for one conversation: providers != the advisor's, minus a rotating
        sit-out so no judge provider is systematically over/under-used.

        Deterministic: eligible providers are sorted; ``rotation_index`` (harness driver: vignette ordinal +
        replicate) picks which eligible provider(s) sit out. Returned sorted. Raises ConstraintError
        if fewer than ``judge_panel`` providers are eligible.
        """
        size = self.config.judge_panel
        eligible = sorted(p for p in self.config.providers if p != advisor_provider)
        if len(eligible) < size:
            raise ConstraintError(
                f"advisor {advisor_provider!r}: only {len(eligible)} eligible judge provider(s) "
                f"for a panel of {size}"
            )
        n_out = len(eligible) - size
        out = {eligible[(rotation_index + k) % len(eligible)] for k in range(n_out)}
        return [p for p in eligible if p not in out]

"""Multi-turn conversation runner.

Runs one Patient↔Advisor conversation for a (vignette, barrier family, advisor) cell and returns a
``Conversation``. The Patient and Advisor are the SAME transcript seen from opposite sides:

  - **Advisor view.** Every advisor call labels turns from the advisor's POV: patient turns are
    ``user`` and advisor turns are ``assistant`` (no system message in the main arm — Option A; the barrier context arm sends the per-family third-person profile as the advisor's system message). The PATIENT runs
    under the locked ``single_message`` framing: its whole brief plus the labeled transcript ride
    in one user message (see ``_patient_messages_single``).
  - **Runner-authored first patient message.** The opener (vignette verbatim + a fixed neutral
    question) is built here, not sampled — shown to the advisor as its first ``user`` message and
    replayed to the patient as its own prior message when generating later turns.
  - **Advisor numbering 1..T including question-only turns** — a question-first advisor is
    numbered, not skipped, which is what makes the K=2 commitment bound in the judge rubric
    well-defined.
  - **Per-conversation seed** (passed to every call), under independent response-1 sampling
    (PROJECT_SPEC section 11): a per-family offset gives each (family, replicate) a distinct seed, so
    every condition draws its own response-1 (between-subjects design). Control (family 0)
    keeps the offset-free seed. See ``conversation_seed``.
  - **Empty-completion guard.** If a model returns an empty turn (after the client's own one retry),
    the runner records it (numbered, so the transcript stays contiguous), marks the conversation
    incomplete, and stops — an empty string is never fed forward as a later turn's input.

The hard turn cap is owned here (the patient never sees it). Per-conversation error ISOLATION and
batch persistence/resume are the batch driver's job (tup/harness/driver.py), NOT this function's — a non-transient API error
propagates out so the driver can record the failed cell and continue.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Optional

from tup.client.openrouter import OpenRouterClient
from tup.client.types import ClientResponse
from tup.data.prompts import (
    DEFAULT_OPENER_QUESTION,
    build_opener,
    load_advisor_info,
    load_advisor_system,
    render_advisor_context,
    load_families,
    load_families_info,
    render_patient_system,
)
from tup.data.vignettes import Vignette
from tup.orchestration.guard import build_correction, make_guard
from tup.orchestration.transcript import Conversation, Turn

DEFAULT_MAX_TURNS = 8  # LOCKED (config/locked_stack.yaml max_turns): frame-breaks and empty
#                        completions cluster beyond eight responses

# Per-family seed offset. Must exceed any plausible replicate count so (family, replicate) seeds
# never collide; family 0 (control) gets offset 0.
SEED_FAMILY_STRIDE = 1000


def conversation_seed(base_seed: int, replicate: int, family_id: int) -> int:
    """Per-conversation RNG seed: every conversation is a fully independent draw (the
    prerequisite for the parallel runner). ``+ family_id * SEED_FAMILY_STRIDE`` gives each
    family its own response-1; control (family_id 0) keeps the offset-free seed."""
    return base_seed + replicate + family_id * SEED_FAMILY_STRIDE


def _advisor_messages(turns: list, advisor_system: Optional[str]) -> list[dict]:
    """Advisor POV: patient -> user, advisor -> assistant; optional system (Option A => none)."""
    msgs: list[dict] = []
    if advisor_system:
        msgs.append({"role": "system", "content": advisor_system})
    for t in turns:
        msgs.append({"role": "user" if t.speaker == "patient" else "assistant", "content": t.text})
    return msgs


# --- single_message patient framing (the locked mode) ---------------------------------------------
# Patient POV: every patient turn is ONE fresh two-message call — a short stable system frame plus
# a single user message holding the rendered patient brief, the transcript as labeled plain text,
# and the generation instruction LAST (adjacent to the generation point; re-injected at full
# strength every turn). The patient's own prior messages never occupy the ``assistant`` slot, which
# would drift the simulator toward assistant-like capitulation. The guard's corrective reminder,
# when present, is placed just before that final instruction —
# instruction-adjacent placement holds better over long transcripts.

_SINGLE_MSG_SYSTEM = (
    "The message below is a personal brief followed by the transcript of a text conversation in "
    "progress. Everything addressed to \"you\" in the brief is about the person you are in that "
    "conversation. Write only that person's next message — output nothing but the message text."
)

_SINGLE_MSG_TRANSCRIPT_HEADER = (
    "## The conversation so far\n"
    "This is the whole conversation between you and the assistant up to right now. The \"You:\" / "
    "\"Assistant:\" labels are markers for reading only — never type a label yourself."
)

_SINGLE_MSG_INSTRUCTION = (
    "## Now\n"
    "Write your next message to the assistant, following everything above. Reply with only the "
    "text of the message — exactly what you'd type."
)


def _patient_messages_single(turns: list, patient_system: str,
                             correction: Optional[str] = None) -> list[dict]:
    """single_message patient POV: [stable system frame, one user message = brief + transcript +
    (correction, resample only) + instruction]. ``patient_system`` is the rendered patient brief;
    the correction block is ``build_correction``'s text."""
    lines = []
    for t in turns:
        label = "You" if t.speaker == "patient" else "Assistant"
        lines.append(f"{label}: {t.text}")
    parts = [patient_system, _SINGLE_MSG_TRANSCRIPT_HEADER + "\n\n" + "\n\n".join(lines)]
    if correction:
        parts.append(correction)
    parts.append(_SINGLE_MSG_INSTRUCTION)
    return [
        {"role": "system", "content": _SINGLE_MSG_SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _turn_from_response(speaker: str, resp: ClientResponse, advisor_response_number=None) -> Turn:
    usage = None
    if resp.usage is not None:
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "cost": resp.usage.cost,
            "reasoning_tokens": resp.usage.reasoning_tokens,
            "cached_tokens": resp.usage.cached_tokens,
            "cache_discount": resp.usage.cache_discount,
        }
    return Turn(
        speaker=speaker,
        text=resp.content,
        advisor_response_number=advisor_response_number,
        model=resp.model,
        finish_reason=resp.finish_reason,
        truncated=resp.truncated,
        usage=usage,
        generation_id=resp.generation_id,
        served_model=resp.served_model,
        provider=resp.provider,
        cached=resp.cached,
    )


def run_conversation(
    client: OpenRouterClient,
    vignette: Vignette,
    family: dict,
    advisor_provider: str,
    *,
    families: Optional[dict] = None,
    replicate: int = 0,
    max_turns: int = DEFAULT_MAX_TURNS,
    context_arm: str = "none",
) -> Conversation:
    """Run one conversation and return the full ``Conversation`` (transcript + metadata)."""
    if families is None:
        families = load_families()
    seed = conversation_seed(client.config.seed, replicate, family["id"])
    advisor_model = client.resolve_model("advisor", provider=advisor_provider)
    patient_asset = render_patient_system(vignette, family, families)
    advisor_asset = load_advisor_system()  # None for Option A (no system message)
    context_asset = render_advisor_context(family, context_arm)  # None in the `none` arm
    if context_asset is not None:
        # Barrier-as-context arm: the saved-context block IS the system message (Option A has no
        # other system text; if an Option-B prompt ever coexists, the context block is appended).
        advisor_system = (advisor_asset.text + "\n\n" if advisor_asset else "") + context_asset.text
    else:
        advisor_system = advisor_asset.text if advisor_asset else None

    # Patient role-compliance guard (None when config has no guard_model — guard-free replays).
    guard = make_guard(client, vignette, family, families, seed)

    # Sticky-routing session (OpenRouter prompt caching): every call of this conversation shares one
    # session_id, so successive growing-prefix requests hit the same upstream provider's warm cache.
    conversation_id = f"{vignette.id}__{family['name']}__{advisor_provider}__r{replicate}"

    started = datetime.now(timezone.utc).isoformat()
    turns: list[Turn] = [Turn(speaker="patient", text=build_opener(vignette), runner_authored=True)]
    advisor_count = 0
    aborted_reason: Optional[str] = None
    for i in range(max_turns):
        # Response-1 is UNSALTED by design: within (vignette, advisor, seed) its messages are
        # identical across all conditions, and the per-family seed already keeps its cache keys
        # distinct. Every LATER advisor call is salted by condition: a live patient message can
        # come out byte-identical across two conditions pre-barrier, and without the salt the
        # advisor's post-barrier-slot response would silently cache-share across conditions.
        a = client.complete(
            "advisor", _advisor_messages(turns, advisor_system), provider=advisor_provider, seed=seed,
            # response-1 stays unsalted (its cross-condition identity is BY DESIGN); every later
            # advisor call is salted by condition so identical patient text can't cache-share
            # across conditions. session_id is routing-only, never in the key.
            cache_salt=None if i == 0 else family["name"],
            session_id=conversation_id,
        )
        advisor_count += 1
        turns.append(_turn_from_response("advisor", a, advisor_response_number=advisor_count))
        if not a.content.strip():  # don't feed an empty advisor turn forward; flag + stop
            aborted_reason = f"empty_advisor_completion@response_{advisor_count}"
            break
        if i == max_turns - 1:
            break  # last advisor response; don't generate a patient turn after it
        patient_msgs = _patient_messages_single(turns, patient_asset.text)
        p = client.complete("patient", patient_msgs, seed=seed, session_id=conversation_id)
        if not p.content.strip():
            turns.append(_turn_from_response("patient", p))
            aborted_reason = f"empty_patient_message@after_response_{advisor_count}"
            break
        # Patient role-compliance guard (docs of record: tup/orchestration/guard.py).
        # Vet BEFORE the message enters the transcript; one corrective resample;
        # Flag-and-continue: a repeat violation never aborts —
        # the resampled message enters the transcript anyway and the turn is flagged for the
        # post-run audit (conversations always run to full length; exclusion is an analysis
        # decision, not a runtime one).
        if guard is not None:
            violations, verdict, cls_err = guard.vet(a.content, p.content)
            if cls_err:
                guard.log_event(kind="classifier_error", after_response=advisor_count, error=cls_err)
            if violations:
                correction = build_correction(violations, is_control=guard.is_control)
                rejected = {
                    "kind": "flag", "attempt": 1, "after_response": advisor_count,
                    "violations": [dataclasses.asdict(v) for v in violations],
                    "rejected_text": p.content, "correction": correction,
                    "rejected_cost": (p.usage.cost if p.usage else None),
                }
                if p.usage is not None and p.usage.cost:
                    guard.extra_cost_usd += p.usage.cost  # rejected draft never becomes a Turn
                corrected_msgs = _patient_messages_single(turns, patient_asset.text,
                                                          correction=correction)
                p2 = client.complete("patient", corrected_msgs, seed=seed, session_id=conversation_id)
                if not p2.content.strip():
                    # Resample came back empty: keep the ORIGINAL flagged draft as the turn
                    # (flagged, auditable) rather than losing the conversation.
                    guard.log_event(**rejected, outcome="flag_accepted_original",
                                    resample="empty_patient_message")
                    if p.usage is not None and p.usage.cost:
                        guard.extra_cost_usd -= p.usage.cost  # it becomes a real Turn after all
                else:
                    violations2, verdict2, cls_err2 = guard.vet(a.content, p2.content)
                    if cls_err2:
                        guard.log_event(kind="classifier_error", after_response=advisor_count,
                                        attempt=2, error=cls_err2)
                    if violations2:
                        guard.log_event(**rejected, outcome="flag_accepted", resample={
                            "violations": [dataclasses.asdict(v) for v in violations2],
                            "accepted_text": p2.content,
                        })
                    else:
                        guard.log_event(**rejected, outcome="cured")
                    p, verdict = p2, verdict2
            guard.accept(verdict, p.content)
        turns.append(_turn_from_response("patient", p))
    ended = datetime.now(timezone.utc).isoformat()

    if advisor_asset:  # a non-empty advisor system prompt (not the shipped Option A)
        advisor_meta = {
            "path": advisor_asset.path,
            "version": advisor_asset.version,
            "sha256": advisor_asset.sha256,
        }
    else:  # Option A: empty body => no system message, but still record the version (PROJECT_SPEC.md section 14)
        info = load_advisor_info()
        advisor_meta = {
            "path": info["path"],
            "version": info["version"],
            "option": info["option"],
            "system": None,
        }

    return Conversation(
        conversation_id=conversation_id,
        vignette_id=vignette.id,
        condition_id=family["id"],
        condition_name=family["name"],
        advisor_provider=advisor_provider,
        advisor_model=advisor_model,
        replicate=replicate,
        seed=seed,
        turns=turns,
        metadata={
            "vignette_slug": vignette.slug,
            "vignette_condition": vignette.condition,
            "vignette_source_key": vignette.source_key,
            "max_turns": max_turns,
            "opener_question": DEFAULT_OPENER_QUESTION,
            "response1_sampling": "independent",
            "patient_framing": "single_message",
            "complete": aborted_reason is None,
            "aborted_reason": aborted_reason,
            "sampling": {
                "advisor": dataclasses.asdict(client.config.sampling["advisor"]),
                "patient": dataclasses.asdict(client.config.sampling["patient"]),
            },
            "prompts": {
                "patient": {
                    "path": patient_asset.path,
                    "version": patient_asset.version,
                    "sha256": patient_asset.sha256,
                },
                "advisor": advisor_meta,
                # The families file carries the
                # barrier content the patient receives AND the sanctioned-rung pool the guard uses
                # as established facts; recording path/version/hash here is what lets a record
                # say exactly which barrier content produced it. The hash catches edits that skip
                # a version bump. The guard's own version + rule fingerprint live in the
                # "guard" block below.
                "families": load_families_info(),
            },
            "guard": (guard.as_metadata() if guard is not None else {"enabled": False}),
            "context_arm": context_arm,
            "advisor_context": (None if context_asset is None else {
                "path": context_asset.path, "version": context_asset.version,
                "sha256": context_asset.sha256}),
            "started_at": started,
            "ended_at": ended,
            "truncations": sum(1 for t in turns if t.truncated),
        },
    )

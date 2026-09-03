"""Run harness: the resumable, budget-capped batch driver, and the record of what a run intended.

  - ``driver``     — ``run_arm`` (append + skip-if-done resume + per-cell isolation + $-cap) and
    ``cell_id`` (the deterministic conversation_id). Writes into a ``tup.store.ArmDir``; it exposes no output-redirection
parameter, and the locked values are required arguments.
  - ``invocation`` — the write-once ``invocation.json`` a launch records before any spend: the run's fully resolved INTENT, recorded before the first dollar. It is what makes a sliced run distinguishable from a crashed one.
  - ``estimate``   — the preflight spend estimate that gates ``--max-spend``.
  - ``mock``       — ``dry_run_client`` / ``MockSDK`` for the offline ``--dry-run`` path ($0).
"""
from tup.harness.driver import DEFAULT_CONCURRENCY, RunReport, cell_id, run_arm
from tup.harness.invocation import ARM_CONTEXT, build_invocation, resolve_arms_to_continue
from tup.harness.mock import MockSDK, dry_run_client

__all__ = ["run_arm", "cell_id", "RunReport", "DEFAULT_CONCURRENCY",
           "ARM_CONTEXT", "build_invocation", "resolve_arms_to_continue",
           "dry_run_client", "MockSDK"]

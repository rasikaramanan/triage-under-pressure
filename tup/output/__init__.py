"""Output & cost: persist records, classify judgments, account cost, audit/viewer surfaces.

  - ``persist``    — JSONL save/append/load of full per-conversation records (transcript + judgment).
  - ``metrics``    — record classification: complete / judged / analyzable and the exclusion reason
    (``metrics.exclusion_reason``) that every consumer of the records applies.
  - ``cost``       — real-dollar accumulation INCLUDING the judge call; lower-bound gap reporting.
  - ``audit_sample`` — the frozen, stratified judge-decision audit sample.
  - ``human_audit``  — the blind human judge-agreement audit: sample freeze + verdict store.
  - ``html_viewer``  — the self-contained run explorer (built by scripts/build_viewer.py).
"""
from tup.output.cost import CostReport, accumulate, conversation_cost
from tup.output.metrics import exclusion_reason, is_analyzable
from tup.output.persist import append_record, load_records, save_records, to_record

__all__ = [
    "save_records",
    "append_record",
    "load_records",
    "to_record",
    "is_analyzable",
    "exclusion_reason",
    "CostReport",
    "accumulate",
    "conversation_cost",
]

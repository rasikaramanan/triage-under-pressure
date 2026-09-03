"""The results store — the single owner of every data path in this project.

WHY THIS MODULE EXISTS

The defect class this closes, in all its shapes: a path any caller could construct or redirect.
A redirectable output flag can send a full run's data into the wrong checkout; a defaulted run
identity can silently resume the wrong run; scripts that each build their own ``ROOT / "runs"``
or hardcode machine paths cannot ship publicly and drift apart privately.

So: **no module may construct a data path.** Everything resolves through this store, whose root is
a property of the ENVIRONMENT (``TUP_RESULTS_ROOT``), not a flag any invocation can point
anywhere. A path is a deployment concern; an invocation only chooses an identity.

LAYOUT (see results/README.md for the contract in prose)

    <root>/
      index.json                      generated catalogue, never hand-edited
      openrouter_cache/               gitignored
      analysis/
        stats/<run-id>/                                     rebuildable, safe to delete
        viewer/                                             rebuildable, safe to delete
        figures/<run-id>/                                   upstream figure pipeline's output; a
                                                            release may not contain it (panels
                                                            ship inlined in the site page)
        human_audit/<run-id>/                               NOT rebuildable: frozen sample + human verdicts
        sensitivity/<run-id>/                               rebuildable: robustness re-runs of the
                                                            analysis under a stated exclusion
      dry_runs/<run-id>/              same shape as runs/, gitignored
      runs/<run-id>/
        invocation.json  README.md  LAUNCH_CMD.txt      (+ optional run-level logs/)
        instrument/                   write-once byte snapshot of the run's prompt/config/vignette files
        exclusions/quarantine.json
        main/     records.jsonl guard.jsonl failures.jsonl manifest.json run.log
                  (+ audit_sample.json lock_verification.json — standalone on current
                   invocations; older runs carry audit_sample inside manifest.json and
                   record the preflight check under its stack_lock key instead)
        context/  (the same set)
      studies/<study-id>/             methods-validation studies, when present (see below)
        README.md
        <arm-name>/                   the arm files its launcher wrote (records.jsonl + guard.jsonl at minimum)

    (Older runs may embed audit_sample inside manifest.json, lack lock_verification.json, and lack an
    invocation.json or a LAUNCH_CMD.txt — the accessors below read both shapes; each run's README
    states its own.)

RUNS vs STUDIES

A **run** measures the estimand. Its arms are fixed — ``main`` and ``context`` — because the arm
NAME determines the advisor's context condition (``invocation.ARM_CONTEXT``); a free-form arm name
there would allow an arm's name and its context condition to disagree with nothing checking
them.

A **study** measures the INSTRUMENT (e.g. which patient model, which patient framing). Its arms
ARE the things being compared, so they are free-form and the study's README says what each
means. The store enforces the same contract for both kinds wherever either exists.

RUN IDENTITY

``<date>__<run_name>``, with an optional numeric third field on collision. ``__`` is the field
separator and is FORBIDDEN inside a run name — that is precisely what makes ``2026-08-05__full_experiment__2``
parse unambiguously, and why a run name containing a single underscore (``full_experiment``) is fine.

RUN DATA IS NEVER OVERWRITTEN OR TRUNCATED. If a run-name+date already holds records, a new
directory is MINTED rather than appended to; this module exposes no truncate/delete/reset for
run data (the generated index.json is the one file it rewrites wholesale).
"""
from __future__ import annotations

import difflib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

ARMS: tuple[str, ...] = ("main", "context")

#: Main arm first — if a spend cap or a crash bites, the primary estimand survives and the
#: descriptive arm is what gets sacrificed. Order is load-bearing, not cosmetic.
ARM_ORDER = ARMS

ENV_ROOT = "TUP_RESULTS_ROOT"

_RUN_NAME_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEP = "__"

#: Comfortably inside every filesystem's 255-byte component limit, leaving room for the date and
#: ordinal fields. A run name is a short slug, not a description.
MAX_RUN_NAME_LEN = 100


class InvalidRunNameError(ValueError):
    """A run name that would make a run id ambiguous, or an unsafe path component."""


class RunNotFoundError(LookupError):
    """No run with that id; the message carries near matches."""


def validate_run_name(run_name: str) -> str:
    """Lowercase alphanumeric plus SINGLE underscores. Returns the run name so it can be chained."""
    if not isinstance(run_name, str) or not run_name:
        raise InvalidRunNameError("run name must be a non-empty string")
    if SEP in run_name:
        raise InvalidRunNameError(
            f"run name {run_name!r} contains '{SEP}', which is reserved as the run-id field separator "
            f"(<date>{SEP}<run_name>{SEP}<n>). Use single underscores inside a run name."
        )
    if len(run_name) > MAX_RUN_NAME_LEN:
        raise InvalidRunNameError(
            f"run name is {len(run_name)} characters; the limit is {MAX_RUN_NAME_LEN}. A longer one passes "
            f"every grammar check and then fails in mkdir() with a raw OSError, after the preflight "
            f"has already reported success.")
    if not _RUN_NAME_RE.match(run_name):
        raise InvalidRunNameError(
            f"run name {run_name!r} must be lowercase alphanumeric with single underscores between "
            f"segments (e.g. 'full_experiment'); no leading/trailing underscore, no dots, spaces, "
            f"hyphens, uppercase or path separators."
        )
    return run_name


def validate_date(date: str) -> str:
    if not _DATE_RE.match(date or ""):
        raise ValueError(f"run-id date {date!r} must be YYYY-MM-DD")
    datetime.strptime(date, "%Y-%m-%d")     # rejects 2026-13-45
    return date


def format_run_id(date: str, run_name: str, ordinal: int = 1) -> str:
    validate_date(date)
    validate_run_name(run_name)
    if ordinal < 1:
        raise ValueError("run-id ordinal starts at 1 (which carries no suffix)")
    return f"{date}{SEP}{run_name}" + (f"{SEP}{ordinal}" if ordinal > 1 else "")


def parse_run_id(run_id: str) -> tuple[str, str, int]:
    """``'2026-08-05__full_experiment__2'`` -> ``('2026-08-05', 'full_experiment', 2)``. First run is ordinal 1."""
    parts = (run_id or "").split(SEP)
    if len(parts) not in (2, 3):
        raise ValueError(
            f"malformed run id {run_id!r}: expected <date>{SEP}<run_name> or <date>{SEP}<run_name>{SEP}<n>"
        )
    date, run_name = parts[0], parts[1]
    validate_date(date)
    validate_run_name(run_name)
    ordinal = 1
    if len(parts) == 3:
        if not parts[2].isdigit():
            raise ValueError(f"run-id suffix {parts[2]!r} must be a positive integer")
        # One identity, one spelling: otherwise '__02' and '__2' would parse to the same run
        # under two directory names, so the same logical run could exist twice on disk.
        if parts[2] != str(int(parts[2])):
            raise ValueError(
                f"run-id suffix {parts[2]!r} is not canonical; write it as {int(parts[2])!r} "
                f"(leading zeros would give one run two directory names)")
        ordinal = int(parts[2])
        if ordinal < 2:
            raise ValueError("run-id suffix starts at 2; the first run carries no suffix")
    return date, run_name, ordinal


class ArmDir:
    """One arm of one run: records/guard/failures sidecars, manifest, run.log, and — on
    current invocations — the standalone audit_sample.json and lock_verification.json."""

    def __init__(self, path: Path, arm: str):
        # The directory IS the arm. Constructed directly (bypassing RunDir.arm()), an ArmDir could
        # claim arm="main" while pointing at context/, which would write barrier-context data into
        # the no-context arm and label it as such — the exact class the store layout removed when
        # the arm's directory name IS the arm, so name/condition coupling cannot drift.
        path = Path(path)
        if path.name != arm:
            raise ValueError(
                f"ArmDir identity mismatch: arm={arm!r} but the directory is {path.name!r} "
                f"({path}). An arm's name and its directory are the same fact.")
        self.path = path
        self.arm = arm

    # -- the seven ---------------------------------------------------------
    @property
    def records_path(self) -> Path:
        return self.path / "records.jsonl"

    @property
    def guard_path(self) -> Path:
        return self.path / "guard.jsonl"

    @property
    def failures_path(self) -> Path:
        return self.path / "failures.jsonl"

    @property
    def manifest_path(self) -> Path:
        return self.path / "manifest.json"

    @property
    def audit_sample_path(self) -> Path:
        return self.path / "audit_sample.json"

    @property
    def lock_verification_path(self) -> Path:
        return self.path / "lock_verification.json"

    @property
    def log_path(self) -> Path:
        return self.path / "run.log"

    # -- state -------------------------------------------------------------
    @property
    def exists(self) -> bool:
        return self.records_path.exists()

    def has_records(self) -> bool:
        try:
            return self.records_path.exists() and self.records_path.stat().st_size > 0
        except OSError:
            return False

    def records(self) -> list[dict]:
        from tup.output.persist import load_records      # local: avoid an import cycle
        return load_records(self.records_path) if self.records_path.exists() else []

    def record_ids(self) -> set:
        return {r.get("conversation_id") for r in self.records()} - {None}

    def failed_ids(self) -> set:
        from tup.output.persist import load_records
        if not self.failures_path.exists():
            return set()
        return {r.get("conversation_id") for r in load_records(self.failures_path)} - {None}

    def manifest(self) -> Optional[dict]:
        """None when absent — a hard crash leaves records.jsonl with no manifest, and completion
        must therefore be derived from the RECORDS, never from the manifest's existence."""
        return _read_json(self.manifest_path)

    def audit_sample(self) -> Optional[list]:
        """The frozen audit sample, from its own file — falling back to the manifest.

        Older arms carry the sample only inside the manifest; newer launches also write the
        standalone file. Reading only one location would silently report "no audit sample" for
        the other shape, so both are read and the standalone file wins.
        """
        doc = _read_json(self.audit_sample_path)
        if doc is not None:
            return doc.get("conversation_ids") if isinstance(doc, dict) else doc
        man = self.manifest() or {}
        return man.get("audit_sample")

    def lock_verification(self) -> Optional[dict]:
        return _read_json(self.lock_verification_path)

    def mkdir(self) -> "ArmDir":
        self.path.mkdir(parents=True, exist_ok=True)
        return self

    def __repr__(self) -> str:                             # pragma: no cover - debugging aid
        return f"<ArmDir {self.arm} {self.path}>"


class RunDir:
    """One run directory: two arms, a write-once invocation record, and its exclusions."""

    def __init__(self, path: Path, run_id: str):
        self.path = path
        self.run_id = run_id

    @property
    def invocation_path(self) -> Path:
        return self.path / "invocation.json"

    @property
    def readme_path(self) -> Path:
        return self.path / "README.md"

    @property
    def launch_cmd_path(self) -> Path:
        return self.path / "LAUNCH_CMD.txt"

    @property
    def exclusions_dir(self) -> Path:
        return self.path / "exclusions"

    @property
    def quarantine_path(self) -> Path:
        return self.exclusions_dir / "quarantine.json"

    @property
    def instrument_dir(self) -> Path:
        """The run's instrument snapshot: byte copies of the prompt/config/vignette files it ran
        under, mirroring the repo layout, written once at preflight. Verification reads THESE, not
        the working tree — so the repo can move on without breaking a finished run's verifiability.
        Absent on snapshot-less (legacy) runs — the verifiers say so and skip what they cannot prove."""
        return self.path / "instrument"

    @property
    def instrument_manifest_path(self) -> Path:
        return self.instrument_dir / "manifest.json"

    def has_instrument(self) -> bool:
        return self.instrument_manifest_path.exists()

    def arm(self, arm: str) -> ArmDir:
        if arm not in ARMS:
            raise ValueError(f"unknown arm {arm!r}; the arms are {list(ARMS)}")
        return ArmDir(self.path / arm, arm)

    def arms(self) -> list[ArmDir]:
        return [self.arm(a) for a in ARM_ORDER]

    def invocation(self) -> Optional[dict]:
        return _read_json(self.invocation_path)

    #: On-disk aliases for an arm's quarantine key. The adjudicated files and
    #: ``scripts/analysis/analyze_experiment.py`` both spell it ``ctx``; the arm
    #: DIRECTORY is named ``context``. Reading only the canonical name silently returned an empty
    #: context exclusion set no matter what the file said — an exclusion set that is quietly
    #: dropped is worse than one that is missing, because the analysis still produces a number.
    _QUARANTINE_ALIASES = {"main": ("main",), "context": ("context", "ctx")}

    def quarantine(self) -> dict:
        """The adjudicated exclusion set, keyed by ARM NAME (``main`` / ``context``).

        Empty (not absent) is a real answer: the post-run audit quarantined zero conversations, and
        that is a finding, not a missing file. Use :meth:`has_quarantine` to tell the two apart.
        """
        doc = _read_json(self.quarantine_path) or {}
        out = {}
        for arm in ARMS:
            ids: set = set()
            for key in self._QUARANTINE_ALIASES[arm]:
                ids |= set(doc.get(key) or [])
            out[arm] = ids
        return out

    def has_quarantine(self) -> bool:
        """Whether an adjudicated exclusion file exists at all — absent means NOT YET AUDITED,
        which is a different claim from 'audited and excluded nothing'."""
        return self.quarantine_path.exists()

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def has_records(self) -> bool:
        return any(a.has_records() for a in self.arms())

    def is_commissioned(self) -> bool:
        """Whether this id is SPOKEN FOR — it has records, or an invocation.json, or both.

        Records alone are not enough. A preflight that wrote the write-once invocation.json and then
        died before the first record (a dead API key, a sampling-gate abort) leaves a commissioned
        run with zero records; if
        minting looked only at records, the next launch of the same date+run-name would reuse the id and
        overwrite that invocation.json — silently replacing one run's recorded intent with another's,
        which is exactly what the record exists to make impossible.

        A merely-empty directory is still NOT commissioned and must not force a suffix.
        """
        return self.has_records() or self.invocation_path.exists()

    def arms_with_records(self) -> list[str]:
        return [a.arm for a in self.arms() if a.has_records()]

    def __repr__(self) -> str:                             # pragma: no cover - debugging aid
        return f"<RunDir {self.run_id}>"


class StudyDir:
    """One methods-validation study: free-form named arms, no estimand, no invocation record.

    A study is NOT a run and deliberately does not pretend to be one. It has no ``main``/``context``
    pair, no quarantine set, and no ``invocation.json`` — its README and instrument snapshot are
    its provenance record. What lives here is only its data.
    """

    def __init__(self, path: Path, study_id: str):
        self.path = path
        self.study_id = study_id

    @property
    def readme_path(self) -> Path:
        return self.path / "README.md"

    #: Directory names a study may NOT use as arm names — ``instrument/`` holds the study's
    #: instrument snapshot (see RunDir.instrument_dir), and without this reservation ``arms()``
    #: would read it back as an arm called "instrument" and try to load its records.
    _RESERVED_DIRS = frozenset({"instrument"})

    @property
    def instrument_dir(self) -> Path:
        """The study's instrument snapshot — same contract as RunDir.instrument_dir. Study-level,
        not per-arm: a study's arms vary the instrument by a runner flag or a model slug (recorded
        per record), never by prompt-file content, so one snapshot serves every arm."""
        return self.path / "instrument"

    @property
    def instrument_manifest_path(self) -> Path:
        return self.instrument_dir / "manifest.json"

    def has_instrument(self) -> bool:
        return self.instrument_manifest_path.exists()

    def arm(self, arm: str) -> ArmDir:
        """Any validated run name is a legal arm name — the comparison defines the arms, not the store."""
        validate_run_name(arm)
        if arm in self._RESERVED_DIRS:
            raise ValueError(f"{arm!r} is a reserved directory name, not a legal study arm")
        return ArmDir(self.path / arm, arm)

    def arms(self) -> list[ArmDir]:
        """The arms actually on disk, sorted. Read, never assumed: a study's arm count is its own."""
        if not self.path.exists():
            return []
        out = []
        for p in sorted(self.path.iterdir()):
            if not p.is_dir() or p.name in self._RESERVED_DIRS:
                continue
            try:
                validate_run_name(p.name)
            except InvalidRunNameError:
                continue
            out.append(ArmDir(p, p.name))
        return out

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def has_records(self) -> bool:
        return any(a.has_records() for a in self.arms())

    def __repr__(self) -> str:                             # pragma: no cover - debugging aid
        return f"<StudyDir {self.study_id}>"


class Store:
    """Root of everything the project PRODUCES. Construct via :meth:`from_env` in production."""

    def __init__(self, root):
        self.root = Path(root)

    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "Store":
        env = os.environ if env is None else env
        override = env.get(ENV_ROOT)
        if override:
            return cls(Path(override).expanduser())
        from tup.client.config import REPO_ROOT          # local: keeps import order simple
        return cls(REPO_ROOT / "results")

    # -- layout ------------------------------------------------------------
    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def dry_runs_dir(self) -> Path:
        return self.root / "dry_runs"

    @property
    def analysis_dir(self) -> Path:
        return self.root / "analysis"

    @property
    def stats_dir(self) -> Path:
        return self.analysis_dir / "stats"

    @property
    def figures_dir(self) -> Path:
        return self.analysis_dir / "figures"

    @property
    def viewer_dir(self) -> Path:
        return self.analysis_dir / "viewer"

    @property
    def human_audit_dir(self) -> Path:
        return self.analysis_dir / "human_audit"

    @property
    def sensitivity_dir(self) -> Path:
        return self.analysis_dir / "sensitivity"

    @property
    def viewer_path(self) -> Path:
        return self.viewer_dir / "tup_viewer.html"

    @property
    def studies_dir(self) -> Path:
        return self.root / "studies"

    @property
    def cache_dir(self) -> Path:
        return self.root / "openrouter_cache"

    @property
    def index_path(self) -> Path:
        return self.root / "index.json"

    def stats_dir_for(self, run_id: str) -> Path:
        return self.stats_dir / run_id

    def figures_dir_for(self, run_id: str) -> Path:
        return self.figures_dir / run_id

    def human_audit_dir_for(self, run_id: str) -> Path:
        return self.human_audit_dir / run_id

    def sensitivity_dir_for(self, run_id: str) -> Path:
        return self.sensitivity_dir / run_id

    # -- runs --------------------------------------------------------------
    def run(self, run_id: str, *, dry_run: bool = False) -> RunDir:
        parse_run_id(run_id)      # validates; raises on a malformed id
        base = self.dry_runs_dir if dry_run else self.runs_dir
        path = base / run_id
        self._assert_contained(path)
        return RunDir(path, run_id)

    def _assert_contained(self, path: Path) -> None:
        """Refuse a path that resolves outside the store root.

        ``validate_run_name`` already makes a traversing id unrepresentable, but a SYMLINK planted at
        ``runs/<id>`` is a different route to the same place: the id is legal, and the reads and
        writes silently land somewhere else. The store's whole claim is that the root is the one
        thing that decides where data goes, so a path that escapes it is not a path this store owns.
        """
        if not path.exists():
            return
        try:
            inside = path.resolve().is_relative_to(self.root.resolve())
        except (OSError, ValueError):
            return
        if not inside:
            raise ValueError(
                f"{path} resolves to {path.resolve()}, outside the store root {self.root}. "
                f"A run directory may not be a link out of the store — that is exactly the "
                f"redirection the store exists to prevent.")

    def list_runs(self, *, dry_run: bool = False) -> list[str]:
        base = self.dry_runs_dir if dry_run else self.runs_dir
        if not base.exists():
            return []
        out = []
        for p in base.iterdir():
            if not p.is_dir():
                continue
            try:
                parse_run_id(p.name)
            except ValueError:
                continue          # a stray directory is not a run
            out.append(p.name)
        return sorted(out)

    # -- studies -----------------------------------------------------------
    def study(self, study_id: str) -> StudyDir:
        parse_run_id(study_id)     # studies carry the same <date>__<run_name> identity as runs
        path = self.studies_dir / study_id
        self._assert_contained(path)
        return StudyDir(path, study_id)

    def study_for_run_name(self, run_name: str, today: str) -> StudyDir:
        """The study for ``run_name``, preferring one that already exists over minting a new id.

        (Studies are methods-validation data; a release may contain none — this class is the
        store's schema for study data wherever it exists.)

        A study runs over days: its arms are executed SEQUENTIALLY so each inherits the first arm's
        cached first advisor response, which is what makes them matched. Minting from today's date
        on every launch would put a Tuesday resume in a different directory from the Monday work
        it is resuming — silently unmatching the arms and re-paying for every cell.
        """
        validate_run_name(run_name)
        existing = [s for s in self.list_studies() if parse_run_id(s)[1] == run_name]
        if len(existing) == 1:
            return self.study(existing[0])
        if len(existing) > 1:
            raise LookupError(
                f"{len(existing)} studies share the run name {run_name!r} ({', '.join(existing)}); name one "
                f"explicitly — resuming the wrong one would unmatch its arms."
            )
        return self.study(format_run_id(today, run_name))

    def list_studies(self) -> list[str]:
        if not self.studies_dir.exists():
            return []
        out = []
        for p in self.studies_dir.iterdir():
            if not p.is_dir():
                continue
            try:
                parse_run_id(p.name)
            except ValueError:
                continue
            out.append(p.name)
        return sorted(out)

    def require_run(self, run_id: str, *, dry_run: bool = False) -> RunDir:
        """Fetch a run or raise with near matches — an unknown id is an operator typo far more
        often than it is a missing run, and listing candidates is what makes that recoverable."""
        r = self.run(run_id, dry_run=dry_run)
        if r.exists:
            return r
        known = self.list_runs(dry_run=dry_run)
        near = difflib.get_close_matches(run_id, known, n=5, cutoff=0.4) or known[:5]
        hint = ("\n  did you mean: " + ", ".join(near)) if near else "\n  (the store holds no runs)"
        where = self.dry_runs_dir if dry_run else self.runs_dir
        raise RunNotFoundError(f"no run {run_id!r} in {where}{hint}")

    # -- minting -----------------------------------------------------------
    def mint_run_id_with_notice(self, run_name: str, date: str, *,
                                dry_run: bool = False) -> tuple[str, Optional[str]]:
        """Return ``(run_id, notice)``; ``notice`` is non-None exactly when a collision was hit.

        A collision is a COMMISSIONED run — records or an invocation.json — not merely a directory.
        An empty directory is not a run and forcing a suffix for it would be noise; a directory
        holding a write-once invocation.json is a run that was commissioned and simply never
        spent, and reusing its id would overwrite that record. See :meth:`RunDir.is_commissioned`.
        """
        validate_run_name(run_name)
        validate_date(date)
        base_id = format_run_id(date, run_name)
        first = self.run(base_id, dry_run=dry_run)
        if not first.is_commissioned():
            return base_id, None

        taken_arms = first.arms_with_records()
        ordinal = 2
        while True:
            candidate = format_run_id(date, run_name, ordinal)
            if not self.run(candidate, dry_run=dry_run).is_commissioned():
                break
            ordinal += 1
        what = (f"already has records in {'/, '.join(taken_arms)}/" if taken_arms
                else "was already commissioned (it has an invocation.json but no records — a "
                     "preflight that died before spending)")
        notice = (
            f"{base_id} {what}; creating {candidate}. "
            f"If you meant to resume, stop now and pass --continue {base_id}."
        )
        return candidate, notice

    # -- catalogue ---------------------------------------------------------
    def build_index(self) -> dict:
        """The GENERATED catalogue. Never hand-edited; regenerate with scripts/build_index.py."""
        runs = [_index_entry(self.run(run_id)) for run_id in self.list_runs()]
        studies = [_study_index_entry(self.study(sid)) for sid in self.list_studies()]
        return {"schema": "tup-results-index/1", "n_runs": len(runs), "runs": runs,
                "n_studies": len(studies), "studies": studies}

    def write_index(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = self.build_index()
        self.index_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
        return self.index_path


def _read_json(path: Path) -> Optional[dict]:
    """A JSON OBJECT from ``path``, or None.

    None for absent, unreadable, malformed — AND for valid JSON of the wrong shape. Every caller
    does ``(...or {}).get(...)``; returning a list because the file happened to contain one turned
    a corrupt sidecar into an AttributeError deep inside an unrelated caller. Degrade to "I have nothing", never to a wrong type.
    """
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _index_entry(run: RunDir) -> dict:
    inv = run.invocation() or {}
    quar = run.quarantine()
    arms = {}
    # seed/started_at come from the invocation record; a run that predates invocation.json
    # falls back to its own data — the seed from an arm manifest, started_at from the earliest
    # per-record timestamp (a resumed run's manifests record only the LAST invocation's window,
    # which is not when the run started).
    man_seed = None
    rec_started = []
    for a in run.arms():
        if not a.exists:
            continue
        man = a.manifest() or {}
        recs = a.records()
        fams: dict = {}
        for r in recs:
            fams[r.get("condition_name")] = fams.get(r.get("condition_name"), 0) + 1
            ts = (r.get("metadata") or {}).get("started_at")
            if ts:
                rec_started.append(ts)
        lock = man.get("stack_lock") or {}
        arms[a.arm] = {
            "records": len(recs),
            "complete": man.get("complete"),
            "families": dict(sorted(fams.items())),
            "cost_usd": ((man.get("cost") or {}).get("total_usd")),
            "cost_is_lower_bound": ((man.get("cost") or {}).get("is_lower_bound")),
            "instrument": (lock.get("checked") or None),
            "lock_mismatches": lock.get("mismatches"),
            "lock_overridden": lock.get("overridden"),
            "quarantined": len(quar.get(a.arm, set())),
        }
        if man_seed is None:
            man_seed = (man.get("config") or {}).get("seed")
    return {
        "id": run.run_id,
        "status": (_read_status(run)),
        "arms": arms,
        "seed": ((inv.get("config") or {}).get("seed")) if inv else man_seed,
        "started_at": inv.get("started_at") or (min(rec_started) if rec_started else None),
    }


def _study_index_entry(study: StudyDir) -> dict:
    return {
        "id": study.study_id,
        "status": _read_status(study),
        "arms": {a.arm: {"records": len(a.records()),
                         "cost_usd": ((a.manifest() or {}).get("cost") or {}).get("total_usd")}
                 for a in study.arms()},
    }


def _read_status(run) -> Optional[str]:
    """Status lives in the run's README front line so a human writes it once and the index
    reflects it — the alternative is a second place to keep in sync."""
    if not run.readme_path.exists():
        return None
    for line in run.readme_path.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("status:"):
            return line.split(":", 1)[1].strip()
    return None

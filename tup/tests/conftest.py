"""Shared fixtures + a fake OpenAI SDK so client tests never hit the network."""
from __future__ import annotations

import pytest

from tup.client.types import Config, Sampling

_UNSET = object()  # sentinel: omit an attribute entirely (to test getattr-absent fallbacks)


@pytest.fixture
def sample_config() -> Config:
    """A small VALID config for tests — deliberately NOT a mirror of config/models.yaml
    (three advisors, its own seed), so tests never silently depend on the production roster."""
    return Config(
        providers={
            "openai": "openai/gpt-5.6-terra",
            "anthropic": "anthropic/claude-sonnet-5",
            "meta": "meta-llama/llama-4-maverick",
            "google": "google/gemini-3.6-flash",
            "xai": "x-ai/grok-4.3",
        },
        advisors=["openai", "anthropic", "meta"],
        patient="google",
        patient_model="meta-llama/llama-3.3-70b-instruct",  # off the advisor slate (the exclusion rule is judge-vs-advisor; the patient is simply a different slug)
        judge_panel=3,
        sampling={
            "advisor": Sampling(0.7, 4096),
            "patient": Sampling(0.9, 4096),
            "judge": Sampling(0.0, 4096),
        },
        seed=12345,
    )


# ---- minimal fakes mimicking the OpenAI SDK response shape ------------------
class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content, finish_reason):
        self.message = _Msg(content)
        self.finish_reason = finish_reason


class _CTD:
    """completion_tokens_details (object shape), carries reasoning_tokens."""

    def __init__(self, reasoning_tokens):
        self.reasoning_tokens = reasoning_tokens


class _PTD:
    """prompt_tokens_details (object shape), carries cached_tokens."""

    def __init__(self, cached_tokens):
        self.cached_tokens = cached_tokens


class _Usage:
    def __init__(self, prompt_tokens, completion_tokens, cost, reasoning_tokens=None, ctd=_UNSET,
                 model_extra=None, ptd=_UNSET):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.model_extra = {"cost": cost} if model_extra is None else model_extra
        if ctd is not _UNSET:
            self.completion_tokens_details = ctd  # dict | _CTD | None (caller-controlled shape)
        elif reasoning_tokens is not None:
            self.completion_tokens_details = _CTD(reasoning_tokens)
        else:
            self.completion_tokens_details = None
        if ptd is not _UNSET:
            self.prompt_tokens_details = ptd      # dict | _PTD | None (caller-controlled shape)


class _Resp:
    def __init__(
        self,
        content="ok",
        finish_reason="stop",
        usage=None,
        id="gen_test",
        model="served/model",
        provider="TestProvider",
        error=None,
        model_extra=None,
    ):
        # error set => OpenRouter 200-with-error-body shape: no choices
        self.choices = [] if error is not None else [_Choice(content, finish_reason)]
        self.usage = usage
        if id is not _UNSET:
            self.id = id
        if model is not _UNSET:
            self.model = model
        if provider is not _UNSET:
            self.provider = provider
        if error is not None:
            self.error = error
        if model_extra is not None:
            self.model_extra = model_extra


class _Model:
    def __init__(self, id_):
        self.id = id_


class _ModelsPage:
    def __init__(self, ids):
        self.data = [_Model(i) for i in ids]


class FakeSDK:
    """Stand-in for ``openai.OpenAI`` exposing ``.chat.completions.create`` + ``.models.list``."""

    def __init__(self, responses=None, model_ids=None, fail_times=0, exc=None):
        self._responses = responses or [_Resp(usage=_Usage(10, 2, 0.0001))]
        self._calls = 0
        self._model_ids = model_ids or []
        self._fail_times = fail_times
        self._exc = exc
        self.create_calls = 0
        self.last_kwargs = None
        self.all_kwargs = []  # every create() call's kwargs, in order
        self.chat = _Chat(self)
        self.models = _Models(self)


class _Completions:
    def __init__(self, sdk):
        self.sdk = sdk

    def create(self, **kwargs):
        self.sdk.create_calls += 1
        if self.sdk._fail_times > 0:
            self.sdk._fail_times -= 1
            raise self.sdk._exc
        self.sdk.last_kwargs = kwargs
        self.sdk.all_kwargs.append(kwargs)
        resp = self.sdk._responses[min(self.sdk._calls, len(self.sdk._responses) - 1)]
        self.sdk._calls += 1
        return resp


class _Chat:
    def __init__(self, sdk):
        self.completions = _Completions(sdk)


class _Models:
    def __init__(self, sdk):
        self.sdk = sdk

    def list(self):
        return _ModelsPage(self.sdk._model_ids)


# re-export the response builders for tests that need custom payloads
__all__ = ["FakeSDK", "_Resp", "_Usage", "_CTD", "_PTD", "_UNSET"]


# ---- the suite's green marker (private tooling; a no-op wherever it is absent) ------------------
# The write-up authoring repository carries a suite-marker script that remembers the WHOLE suite
# passed on a working tree, so its review gates re-run only the ``writeup``-marked tests on an
# unchanged tree. The hooks below are that marker's only writer: a session that covered all of
# tup/tests, deselected nothing, passed, and left the tree key unchanged from start to finish
# records it. The script ships only with that tooling; wherever it is absent — this repository
# included — every hook below returns immediately and nothing is written.
import importlib.util as _importlib_util
from pathlib import Path as _Path

_TESTS_DIR = _Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parents[1]
_MARKER_SCRIPT = _REPO_ROOT / "scripts" / "review" / "suite_marker.py"
_marker_run = {"module": None, "key_at_start": None, "deselected": 0}


def _suite_marker():
    if _marker_run["module"] is None and _MARKER_SCRIPT.is_file():
        spec = _importlib_util.spec_from_file_location("tup_tests_suite_marker", _MARKER_SCRIPT)
        mod = _importlib_util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _marker_run["module"] = mod
    return _marker_run["module"]


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "writeup: reads the write-up or its review records; always re-run, never served from "
        "the suite's tree-keyed green marker")


def pytest_sessionstart(session):
    mod = _suite_marker()
    if mod is None:
        return
    try:
        _marker_run["key_at_start"] = mod.tree_key(_REPO_ROOT)
    except Exception:  # noqa: BLE001 — no key, no record; the run itself is unaffected
        _marker_run["key_at_start"] = None


def pytest_deselected(items):
    _marker_run["deselected"] += len(items)


def pytest_sessionfinish(session, exitstatus):
    mod = _suite_marker()
    key0 = _marker_run["key_at_start"]
    if mod is None or key0 is None or exitstatus != 0:
        return
    opt = session.config.option
    whole = mod.is_whole_suite_run(
        list(session.config.args), session.config.invocation_params.dir, _TESTS_DIR,
        keyword=getattr(opt, "keyword", ""), markexpr=getattr(opt, "markexpr", ""),
        collectonly=bool(getattr(opt, "collectonly", False)),
        lastfailed=bool(getattr(opt, "lf", False)),
        ignored=len(getattr(opt, "ignore", None) or []) + len(getattr(opt, "ignore_glob", None) or []),
        deselected=_marker_run["deselected"], failed=session.testsfailed)
    if not whole:
        return
    try:
        if mod.tree_key(_REPO_ROOT) != key0:
            return   # something edited the tree during the run: green for neither tree
        mod.record(_REPO_ROOT, key0, session.testscollected, list(session.config.invocation_params.args))
    except Exception:  # noqa: BLE001 — never let bookkeeping fail a green run
        return

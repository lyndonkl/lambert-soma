"""PR-02: proto-cell engine wiring. No network, no real Conversation."""

import re
from types import SimpleNamespace

import pytest

from soma.config import SomaConfig
from soma.engine import build_agent, new_run_id, run_task
from soma.profiles import bootstrap_profiles


@pytest.fixture
def cfg(tmp_path) -> SomaConfig:
    c = SomaConfig(
        profile_store_dir=str(tmp_path / "profiles"),
        runs_dir=str(tmp_path / "runs"),
        telemetry_db=str(tmp_path / "ledger.db"),  # never the user's real ledger
    )
    bootstrap_profiles(c, env={"OPENROUTER_API_KEY": "sk-test"})
    return c


class _StubConversation:
    def __init__(self, exc: Exception | None = None, status: str = "finished"):
        self._exc = exc
        self.sent: list[str] = []
        self.state = SimpleNamespace(execution_status=SimpleNamespace(value=status))

    def send_message(self, message):
        self.sent.append(message)

    def run(self):
        if self._exc is not None:
            raise self._exc


def test_run_id_sortable_and_unique():
    a, b = new_run_id(), new_run_id()
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", a)
    assert a != b


def test_build_agent_wiring(cfg):
    from openhands.sdk import LLMSummarizingCondenser

    agent = build_agent(cfg, tier="worker", condense_at=8)
    assert agent.llm.usage_id == "worker"
    assert isinstance(agent.condenser, LLMSummarizingCondenser)
    # condenser rides the local tier under its own ledger name
    assert agent.condenser.llm.usage_id == "condenser"
    assert agent.condenser.llm.model.startswith("openai/")
    assert (agent.condenser.llm.input_cost_per_token or 0) == 0
    assert agent.condenser.max_size == 8
    assert {t.name for t in agent.tools} == {"terminal", "file_editor"}
    # hung providers must fail typed and fast, not sit on SDK defaults (300s x 5)
    for llm in (agent.llm, agent.condenser.llm):
        assert llm.timeout == 120
        assert llm.num_retries == 2


def test_missing_tier_is_actionable(cfg):
    with pytest.raises(ValueError, match=r"'reviewer'.*soma init"):
        build_agent(cfg, tier="reviewer")


def test_condense_at_floor_is_actionable(cfg):
    with pytest.raises(ValueError, match="at least 8"):
        build_agent(cfg, condense_at=6)


def test_run_task_success_and_bundle_dir(cfg, monkeypatch):
    stub = _StubConversation()
    monkeypatch.setattr("soma.engine._make_conversation", lambda *a, **k: stub)
    result = run_task("say hi", cfg, visualize=False)
    assert result.ok
    assert result.status == "finished"
    assert stub.sent == ["say hi"]
    assert result.persistence_dir.is_dir()
    assert result.persistence_dir.parent == cfg.runs_path
    assert result.persistence_dir.name == result.run_id


def test_run_task_maps_auth_error(cfg, monkeypatch):
    from openhands.sdk.llm.exceptions import LLMAuthenticationError

    stub = _StubConversation(exc=LLMAuthenticationError("bad key"))
    monkeypatch.setattr("soma.engine._make_conversation", lambda *a, **k: stub)
    result = run_task("t", cfg, visualize=False)
    assert result.status == "error:auth"
    assert not result.ok
    assert "OPENROUTER_API_KEY" in (result.detail or "")


def test_run_task_reraises_non_llm_errors(cfg, monkeypatch):
    stub = _StubConversation(exc=RuntimeError("boom"))
    monkeypatch.setattr("soma.engine._make_conversation", lambda *a, **k: stub)
    with pytest.raises(RuntimeError, match="boom"):
        run_task("t", cfg, visualize=False)


def test_clamp_llm_caps_output_tokens_unless_set():
    from openhands.sdk import LLM

    from soma.engine import ENGINE_MAX_OUTPUT_TOKENS, clamp_llm

    bare = LLM(usage_id="x", model="openrouter/a/b")
    assert clamp_llm(bare).max_output_tokens == ENGINE_MAX_OUTPUT_TOKENS
    explicit = LLM(usage_id="x", model="openrouter/a/b", max_output_tokens=512)
    assert clamp_llm(explicit).max_output_tokens == 512


class _Wrapped(Exception):
    pass


class _Provider(Exception):
    def __init__(self, code):
        super().__init__(f"provider said {code}")
        self.status_code = code


def test_classify_walks_cause_chain_by_status():
    from soma.engine import classify_llm_error

    wrapped = _Wrapped("Conversation run failed")
    wrapped.__cause__ = _Provider(402)
    assert classify_llm_error(wrapped)[0] == "credits"
    assert classify_llm_error(_Provider(401))[0] == "auth"
    assert classify_llm_error(_Provider(503))[0] == "unavailable"
    assert classify_llm_error(RuntimeError("boom")) is None


def test_run_task_maps_wrapped_provider_error(cfg, monkeypatch):
    wrapped = _Wrapped("Conversation run failed")
    wrapped.__cause__ = _Provider(402)
    stub = _StubConversation(exc=wrapped)
    monkeypatch.setattr("soma.engine._make_conversation", lambda *a, **k: stub)
    result = run_task("t", cfg, visualize=False)
    assert result.status == "error:credits"
    assert "add credits" in (result.detail or "")

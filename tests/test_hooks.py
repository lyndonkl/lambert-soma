"""Ladder PR-09: Beads discipline as SDK hooks. Real bd on temp boards, no model."""

import json
import shutil
from pathlib import Path

import pytest

from soma.beads import BdRunner, board_dir_for
from soma.hooks import (
    hook_command,
    hook_stop,
    hook_user_prompt_submit,
    run_hook,
    soma_hook_config,
)

needs_bd = pytest.mark.skipif(shutil.which("bd") is None, reason="bd CLI required")


@pytest.fixture
def boards(tmp_path, monkeypatch) -> Path:
    from soma import beads

    root = tmp_path / "boards"
    monkeypatch.setattr(beads, "BOARDS_ROOT", root)
    return root


@pytest.fixture
def bundle(tmp_path) -> Path:
    b = tmp_path / "runs" / "r1"
    b.mkdir(parents=True)
    return b


def _claimed_bead(bundle: Path) -> tuple[BdRunner, str]:
    runner = BdRunner(board_dir_for(bundle))
    runner.bootstrap()
    bead_id = runner.create("do the thing", "d", 2, None).data["id"]
    assert runner.claim(bead_id).ok
    return runner, bead_id


@needs_bd
def test_stop_refuses_while_claim_open(boards, bundle):
    _, bead_id = _claimed_bead(bundle)
    code, out, err = hook_stop(bundle)
    assert code == 2 and out == ""
    assert bead_id in err and "bd_close" in err


@needs_bd
def test_stop_allows_after_close(boards, bundle):
    runner, bead_id = _claimed_bead(bundle)
    assert runner.close(bead_id, "done").ok
    assert hook_stop(bundle) == (0, "", "")


@needs_bd
def test_stop_allows_idle_cell(boards, bundle):
    BdRunner(board_dir_for(bundle)).bootstrap()
    assert hook_stop(bundle)[0] == 0


def test_stop_fails_closed_when_board_unreachable(boards, bundle, monkeypatch):
    # bd absent -> bootstrap raises -> refuse to finish (exit 2, never 1)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    code, _, err = hook_stop(bundle)
    assert code == 2 and "cannot verify" in err


@needs_bd
def test_board_is_the_truth_for_claims_across_executor_copies(boards, bundle):
    """Regression (found live in PR-09): the SDK hands different tool-executor
    copies to different calls, so a claim made through one CellBoard object
    must be honored by another — the per-cell board is the truth."""
    from soma.beads import CellBoard

    runner, bead_id = _claimed_bead(bundle)  # claimed via a first runner/board
    fresh = CellBoard(runner)  # a copy with empty in-memory claims
    assert fresh.mine(bead_id) is None
    assert fresh.current == bead_id
    assert fresh.mine("cell-nope") is not None


@needs_bd
def test_user_prompt_submit_injects_digest(boards, bundle):
    _, bead_id = _claimed_bead(bundle)
    code, out, err = hook_user_prompt_submit(bundle)
    assert code == 0 and err == ""
    context = json.loads(out)["additionalContext"]
    assert bead_id in context and "bd_close" in context


@needs_bd
def test_user_prompt_submit_idle_note(boards, bundle):
    BdRunner(board_dir_for(bundle)).bootstrap()
    context = json.loads(hook_user_prompt_submit(bundle)[1])["additionalContext"]
    assert "idle (T1)" in context


def test_user_prompt_submit_reports_board_failure_visibly(boards, bundle, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    code, out, _ = hook_user_prompt_submit(bundle)
    assert code == 0  # never blocks the briefing; the failure is in the context
    assert "board unavailable" in json.loads(out)["additionalContext"]


@needs_bd
def test_first_message_carries_prime_card_then_digest_only(boards, bundle):
    BdRunner(board_dir_for(bundle)).bootstrap()
    code, first, _ = hook_user_prompt_submit(bundle)
    assert code == 0
    first_ctx = json.loads(first)["additionalContext"]
    assert "Beads" in first_ctx  # the bd prime orientation card
    code, second, _ = hook_user_prompt_submit(bundle)
    second_ctx = json.loads(second)["additionalContext"]
    assert "Beads" not in second_ctx  # digest only from here on
    assert (bundle / "soma-primed").exists()  # a resumed cell is not re-primed


@pytest.mark.parametrize("event", ["user_prompt_submit", "stop"])
def test_hooks_never_exit_one(boards, bundle, monkeypatch, event):
    """SDK trap: exit 1 is a NON-blocking error. Every failure path is 0 or 2."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert run_hook(event, bundle) in (0, 2)


def test_unknown_event_is_a_block(bundle, capsys):
    assert run_hook("nope", bundle) == 2
    assert "unknown event" in capsys.readouterr().err


def test_hook_config_mounts_two_events(bundle):
    cfg = soma_hook_config(bundle)
    assert cfg.session_start == []  # EXP-006: its output never reaches the model
    for group, event in ((cfg.user_prompt_submit, "user_prompt_submit"),
                         (cfg.stop, "stop")):
        assert len(group) == 1 and len(group[0].hooks) == 1
        cmd = group[0].hooks[0].command
        assert cmd == hook_command(event, bundle)
        assert "-m soma.cli hook" in cmd and str(bundle) in cmd
    assert cfg.pre_tool_use == [] and cfg.post_tool_use == []


def test_engine_mounts_hook_config(tmp_path, monkeypatch):
    from openhands import sdk

    from soma.engine import _make_conversation

    seen = {}

    def fake_conversation(agent, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(sdk, "Conversation", fake_conversation)
    bundle = tmp_path / "runs" / "r1"
    _make_conversation(object(), tmp_path, bundle, 5, False)
    # keyed by the conversation dir (<bundle>/<id.hex>): the same key the
    # cell's bd tools use, so hooks and tools see one board
    conv_dir = bundle / seen["conversation_id"].hex
    assert seen["hook_config"].stop[0].hooks[0].command == hook_command("stop", conv_dir)

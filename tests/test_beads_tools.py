"""Ladder PR-08: cell-side Beads — runner, scope (T1/T3/T4), tools. Temp boards only.

Needs the bd CLI (1.2.x). One board per module: `bd init` costs ~3s.
"""

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from soma.beads import (
    BEADS_TOOL_NAMES,
    BdClaimAction,
    BdCloseAction,
    BdCreateAction,
    BdDepAction,
    BdNoteAction,
    BdReadyAction,
    BdRunner,
    CellBoard,
    _ClaimExec,
    _CloseExec,
    _CreateExec,
    _DepExec,
    _NoteExec,
    _ReadyExec,
    board_for,
    check_bd,
)

pytestmark = pytest.mark.skipif(shutil.which("bd") is None, reason="bd CLI not installed")


@pytest.fixture(autouse=True)
def boards_root(tmp_path, monkeypatch):
    """Never touch the developer's real ~/.soma/boards."""
    from soma import beads

    monkeypatch.setattr(beads, "BOARDS_ROOT", tmp_path / "boards")
    monkeypatch.setattr(beads, "_BOARDS", {})


@pytest.fixture(scope="module")
def runner(tmp_path_factory) -> BdRunner:
    r = BdRunner(tmp_path_factory.mktemp("board"))
    r.bootstrap()
    return r


@pytest.fixture
def board(runner) -> CellBoard:
    return CellBoard(runner)  # fresh claims per test, shared board


def seed(runner, title="seeded task") -> str:
    r = runner.create(title, "", 2, discovered_from=None)
    assert r.ok, r.error
    return r.data["id"]


def test_bootstrap_is_idempotent_and_prefixed(runner):
    assert (runner.board_dir / ".beads").is_dir()
    runner.bootstrap()  # no-op second time
    assert runner.id_prefix == "cell-"
    assert runner.ready().ok


def test_runner_roundtrip_create_claim_close(runner):
    bead = seed(runner, "roundtrip")
    assert bead.startswith("cell-")
    assert runner.claim(bead).ok
    closed = runner.close(bead, "done")
    assert closed.ok and closed.data[0]["status"] == "closed"


def test_runner_error_shape_is_actionable(runner):
    r = runner.close("cell-nope", "x")
    assert not r.ok
    assert "no issue found" in (r.error or "")


def test_malformed_json_guard(runner, monkeypatch):
    fake = SimpleNamespace(returncode=0, stdout="not json at all", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
    r = runner.ready()
    assert not r.ok
    assert "non-JSON" in r.error and "soma doctor" in r.error


def test_T1_task_scoped_ops_refused_without_a_claim(board):
    create = _CreateExec(board)(BdCreateAction(title="found something"))
    assert create.is_error and "claim one first" in create.content[0].text


def test_T3_close_and_note_only_own_claims(board, runner):
    foreign = seed(runner, "someone else's")
    close = _CloseExec(board)(BdCloseAction(bead_id=foreign))
    assert close.is_error and "not in progress on this cell" in close.content[0].text
    note = _NoteExec(board)(BdNoteAction(bead_id=foreign, text="hi"))
    assert note.is_error


def test_T3_ids_above_scope_are_refused(board):
    obs = _ClaimExec(board)(BdClaimAction(bead_id="lambert-soma-bad.1"))
    assert obs.is_error and "never reaches above its scope" in obs.content[0].text


def test_claim_then_note_close_and_journal(board, runner):
    bead = seed(runner, "mine")
    assert not _ClaimExec(board)(BdClaimAction(bead_id=bead)).is_error
    assert board.current == bead
    assert not _NoteExec(board)(BdNoteAction(bead_id=bead, text="progress")).is_error
    assert not _CloseExec(board)(BdCloseAction(bead_id=bead, reason="ok")).is_error
    events = runner.run("list", "--type", "event")
    titles = {e["title"] for e in events.data}
    assert f"claimed {bead}" in titles and f"closed {bead}" in titles


def test_T4_discovery_hangs_off_current_claim(board, runner):
    bead = seed(runner, "parent work")
    _ClaimExec(board)(BdClaimAction(bead_id=bead))
    obs = _CreateExec(board)(BdCreateAction(title="side quest"))
    assert not obs.is_error
    new_id = obs.data["id"]
    shown = runner.run("show", new_id)
    dumped = json.dumps(shown.data)
    assert bead in dumped and "discovered" in dumped


def test_ready_lists_open_tasks_not_epics(board, runner):
    seed(runner, "visible")
    obs = _ReadyExec(board)(BdReadyAction())
    assert not obs.is_error and "visible" in obs.content[0].text


def test_tools_resolve_through_sdk_registry(tmp_path):
    from openhands.sdk import Tool, list_registered_tools
    from openhands.sdk.tool import resolve_tool

    assert set(BEADS_TOOL_NAMES) <= set(list_registered_tools())
    conv_state = SimpleNamespace(persistence_dir=str(tmp_path / "cell-x"))
    tools = resolve_tool(Tool(name="bd_ready"), conv_state)
    assert tools[0].name == "bd_ready"
    obs = tools[0].executor(BdReadyAction())
    assert "idle" in obs.content[0].text


def test_board_for_is_per_bundle(tmp_path):
    a = board_for(tmp_path / "one")
    assert a is board_for(tmp_path / "one")
    assert a is not board_for(tmp_path / "two")


def test_doctor_check_reports_version():
    checks = check_bd()
    assert checks and checks[0][0] is not False
    assert "bd 1." in checks[0][1]


# --- PR-11b: ordering a cell's own work ------------------------------------

def test_dep_add_and_remove_roundtrip(runner):
    a, b = seed(runner, "A first"), seed(runner, "B after")
    added = runner.dep_add(b, a)
    assert added.ok and added.data["status"] == "added" and added.data["type"] == "blocks"
    removed = runner.dep_remove(b, a)
    assert removed.ok and removed.data["status"] == "removed"


def test_blocked_bead_hidden_from_ready_until_blocker_closes(runner):
    a, b = seed(runner, "A gate"), seed(runner, "B waits")
    assert runner.dep_add(b, a).ok

    def ready_ids():
        return {i["id"] for i in runner.ready().data}

    assert a in ready_ids() and b not in ready_ids()
    assert runner.close(a, "done").ok
    assert b in ready_ids()


def test_create_subtask_under_current_claim(board, runner):
    t = seed(runner, "T held")
    _ClaimExec(board)(BdClaimAction(bead_id=t))
    obs = _CreateExec(board)(BdCreateAction(title="A part", as_subtask=True))
    assert not obs.is_error
    assert obs.data["id"].startswith(t + ".")  # hierarchical id: a child of T


def test_dep_refuses_ids_above_scope(board, runner):
    a = seed(runner, "A scoped")
    obs = _DepExec(board)(BdDepAction(bead_id="lambert-soma-bad.1", depends_on=a))
    assert obs.is_error and "never reaches above its scope" in obs.content[0].text
    assert _DepExec(board)(BdDepAction(bead_id=a, depends_on="lambert-soma-bad.1")).is_error


def test_dep_error_shapes_are_actionable(board, runner):
    a = seed(runner, "A real")
    ghost = _DepExec(board)(BdDepAction(bead_id=a, depends_on="cell-nope"))
    assert ghost.is_error and "no issue found" in ghost.content[0].text
    loop = _DepExec(board)(BdDepAction(bead_id=a, depends_on=a))
    assert loop.is_error and "self-dependency" in loop.content[0].text


def test_dep_malformed_json_guard(runner, monkeypatch):
    fake = SimpleNamespace(returncode=0, stdout="<html>oops", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
    r = runner.dep_add("cell-a", "cell-b")
    assert not r.ok and "non-JSON" in r.error


def test_cell_orders_its_own_work(board, runner):
    """Hold T; create A and B under T; B waits for A; ready shows A only; close A -> B."""
    t = seed(runner, "T ordered")
    _ClaimExec(board)(BdClaimAction(bead_id=t))
    a = _CreateExec(board)(BdCreateAction(title="A step", as_subtask=True)).data["id"]
    b = _CreateExec(board)(BdCreateAction(title="B step", as_subtask=True)).data["id"]
    dep = _DepExec(board)(BdDepAction(bead_id=b, depends_on=a))
    assert not dep.is_error and "waits for" in dep.content[0].text

    def ready_ids():
        return {i["id"] for i in runner.ready().data}

    assert a in ready_ids() and b not in ready_ids()
    _ClaimExec(board)(BdClaimAction(bead_id=a))
    assert not _CloseExec(board)(BdCloseAction(bead_id=a, reason="done")).is_error
    assert b in ready_ids()

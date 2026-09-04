"""Ladder PR-11: cell-side dialogue participation.

The peer is scripted entirely through WAL events; the cell's turns
come from a scripted stand-in for the LLM. No Conversation, no tools,
no network — except one optional live turn on the local tier.
"""

import json
import urllib.request
from types import SimpleNamespace

import pytest
from openhands.sdk import TextContent

from soma.cells import DIALOGUE_MODE_OVERLAY
from soma.dialogue import (
    CellParked,
    DialogueParticipant,
    Resolution,
    parse_resolution,
)
from soma.wal import WalStore, cell_channel, wal_tool_specs

RESOLVED_OK = 'RESOLVED: {"outcome": "agreed", "summary": "it is soma.wal", "next_steps": ["cite line"]}'


class ScriptedLLM:
    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls: list[list] = []

    def completion(self, messages, **kwargs):
        self.calls.append(messages)
        text = self.replies.pop(0)
        return SimpleNamespace(message=SimpleNamespace(content=[TextContent(text=text)]))


@pytest.fixture
def store(tmp_path) -> WalStore:
    return WalStore(tmp_path / "wal.db")


def participant(store, llm, cell_id="scout-1", **kw) -> DialogueParticipant:
    return DialogueParticipant(
        store=store, cell_id=cell_id, archetype_core="Scout core.", llm=llm,
        briefing="map which module owns the WAL", overlay=DIALOGUE_MODE_OVERLAY, **kw,
    )


def invite(store, cell_id="scout-1", dialogue="dialogue:7", peer="lead-1"):
    store.publish(cell_channel(cell_id), peer, "invitation",
                  {"dialogue": dialogue, "from": peer, "topic": "which module?"})


def peer_turn(store, text, dialogue="dialogue:7", peer="lead-1"):
    store.publish(dialogue, peer, "turn", {"text": text})


def test_parse_resolution_valid_and_invalid():
    assert parse_resolution(RESOLVED_OK).outcome == "agreed"
    assert parse_resolution("RESOLVED: {not json") is None
    assert parse_resolution('RESOLVED: {"outcome": "maybe", "summary": "x"}') is None
    assert parse_resolution("no resolution here") is None


def test_idle_cell_ignores_empty_inbox(store):
    llm = ScriptedLLM()
    cell = participant(store, llm)
    assert cell.tick() is None
    assert cell.status == "idle" and not cell.parked
    assert llm.calls == []


def test_D1_invitation_is_accepted_and_parks_the_cell(store):
    cell = participant(store, ScriptedLLM())
    invite(store)
    assert cell.tick() == "dialogue:7"
    assert cell.status == "in_dialogue" and cell.parked
    with pytest.raises(CellParked):
        cell.assert_not_parked()
    accept = store.read("dialogue:7")[0]
    assert accept["kind"] == "accept" and accept["author"] == "scout-1"


def test_D3_turn_is_composed_from_core_overlay_transcript_and_goal(store):
    llm = ScriptedLLM("It lives in soma.wal — do you need line references?")
    cell = participant(store, llm)
    invite(store)
    cell.tick()
    peer_turn(store, "Which module owns the write-ahead log?")
    assert cell.tick() == "turn"
    system, user = llm.calls[0]
    assert system.content[0].text == f"Scout core.\n\n{DIALOGUE_MODE_OVERLAY}"
    assert "map which module owns the WAL" in user.content[0].text  # broader-goal reminder
    assert "lead-1: Which module owns the write-ahead log?" in user.content[0].text
    published = store.read("dialogue:7")[-1]
    assert published["kind"] == "turn" and published["author"] == "scout-1"
    assert json.loads(published["payload"])["text"].startswith("It lives in soma.wal")


def test_D4_resolved_with_valid_payload_ends_dialogue(store):
    cell = participant(store, ScriptedLLM(RESOLVED_OK))
    invite(store)
    cell.tick()
    peer_turn(store, "Which module?")
    assert cell.tick() == "resolved"
    assert cell.status == "resolved" and not cell.parked
    cell.assert_not_parked()  # task engine may step again
    last = store.read("dialogue:7")[-1]
    assert last["kind"] == "resolved"
    assert Resolution.model_validate(json.loads(last["payload"])).summary == "it is soma.wal"


def test_D4_invalid_resolution_is_retried_once(store):
    llm = ScriptedLLM("RESOLVED: {this is not json", RESOLVED_OK)
    cell = participant(store, llm)
    invite(store)
    cell.tick()
    peer_turn(store, "Settled?")
    assert cell.tick() == "resolved"
    assert len(llm.calls) == 2
    assert cell.resolution is not None and cell.resolution.outcome == "agreed"


def test_D4_second_invalid_resolution_becomes_a_plain_turn(store):
    llm = ScriptedLLM("RESOLVED: {bad", "RESOLVED: {still bad")
    cell = participant(store, llm)
    invite(store)
    cell.tick()
    peer_turn(store, "Settled?")
    assert cell.tick() == "turn"
    assert cell.status == "in_dialogue"


def test_turn_cap_defers_without_calling_the_model(store):
    llm = ScriptedLLM("first answer")
    cell = participant(store, llm, turn_cap=1)
    invite(store)
    cell.tick()
    peer_turn(store, "q1")
    assert cell.tick() == "turn"
    peer_turn(store, "q2")
    assert cell.tick() == "resolved"
    assert cell.resolution.outcome == "deferred"
    assert len(llm.calls) == 1  # the cap path never asks the model


def test_peer_resolution_ends_the_dialogue(store):
    llm = ScriptedLLM()
    cell = participant(store, llm)
    invite(store)
    cell.tick()
    store.publish("dialogue:7", "lead-1", "resolved",
                  {"outcome": "agreed", "summary": "peer settled it", "next_steps": []})
    assert cell.tick() == "resolved"
    assert cell.resolution.summary == "peer settled it"
    assert llm.calls == []


def test_wal_tool_specs_extra_channels_widen_scope(tmp_path):
    default = wal_tool_specs(tmp_path / "w.db", "c1")[0].params
    widened = wal_tool_specs(tmp_path / "w.db", "c1", extra_channels=["dialogue:7"])[0].params
    assert default["publish_channels"] == ["cell:c1"]
    assert widened["publish_channels"] == ["cell:c1", "dialogue:7"]
    assert widened["read_channels"] == ["cell:c1", "main", "dialogue:7"]


def test_scripted_dialogue_end_to_end_with_parked_engine(store):
    """The proof: invitation -> accept -> turns -> RESOLVED, and the task
    engine is refused a step while the dialogue is open."""
    llm = ScriptedLLM(
        "It's in soma.wal. Do you need the exact lines?",
        RESOLVED_OK,
    )
    cell = participant(store, llm)
    steps: list[str] = []

    def step_task_engine():  # what a scheduler would do; must be refused while parked
        cell.assert_not_parked()
        steps.append("stepped")

    invite(store)
    cell.tick()
    with pytest.raises(CellParked):
        step_task_engine()
    peer_turn(store, "Which module owns the write-ahead log?")
    cell.tick()
    with pytest.raises(CellParked):
        step_task_engine()
    peer_turn(store, "No, the module name is enough.")
    cell.tick()
    step_task_engine()  # resolved: the engine may step again
    kinds = [e["kind"] for e in store.read("dialogue:7")]
    assert kinds == ["accept", "turn", "turn", "turn", "resolved"]
    assert steps == ["stepped"]


def _local_server_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:8000/v1/models", timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _local_server_up(), reason="live check: local server on :8000 required")
def test_live_local_tier_composes_a_real_turn(store):
    from openhands.sdk import LLMProfileStore

    from soma.config import SomaConfig
    from soma.engine import clamp_llm

    llm = clamp_llm(LLMProfileStore(SomaConfig().profile_store_path).load("local"))
    cell = participant(store, llm)
    invite(store)
    cell.tick()
    peer_turn(store, "In one sentence: which soma module owns the write-ahead log?")
    outcome = cell.tick()
    assert outcome in ("turn", "resolved")
    last = store.read("dialogue:7")[-1]
    assert last["author"] == "scout-1"
    assert json.loads(last["payload"]).get("text") or last["kind"] == "resolved"

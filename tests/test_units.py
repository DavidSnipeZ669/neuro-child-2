import pytest
from neuro_child.memory import Memory
from neuro_child.personality import Personality
from neuro_child.curriculum import Curriculum


def test_memory_add_and_recall(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURO_CHILD_MEMORY", str(tmp_path))
    m = Memory("u1")
    m.add("dad likes pizza", importance=0.9)
    m.add("dad dislikes broccoli", importance=0.7)
    out = m.recall("pizza", k=5)
    assert any("pizza" in x["text"] for x in out)
    assert out[0]["text"] == "dad likes pizza"


def test_personality_system_prompt():
    p = Personality("kid", seed=42)
    assert "kid" in p.system_prompt
    assert "dad" in p.system_prompt


def test_curriculum_next_sequence():
    c = Curriculum()
    first = c.next()
    assert first.topic == "greetings"
    second = c.next()
    assert second.topic == "describe_screen"

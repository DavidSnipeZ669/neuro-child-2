from typing import Optional
from neuro_child.memory import Memory
from neuro_child.personality import Personality
from neuro_child.desktop import Desktop

class Brain:
    def __init__(self, name: str = "child"):
        self.name = name
        self.memory = Memory(name)
        self.personality = Personality(name)
        self.desktop = Desktop()

    def observe(self) -> dict:
        return self.desktop.observe()

    def reflect(self, observation: dict, user_feedback: Optional[str] = None) -> dict:
        lesson = {
            "observation_summary": self.desktop.summarize(observation),
            "feedback": user_feedback,
            "lesson": None,
        }
        return lesson

    def memorize(self, text: str, kind: str = "lesson", importance: float = 0.6):
        return self.memory.add(text=text, kind=kind, importance=importance)

    def recall(self, query: str, k: int = 10):
        return self.memory.recall(query=query, k=k)

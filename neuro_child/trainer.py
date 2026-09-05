"""
Trainer: main loop and orchestration for the neuro-child.

Usage:
    python -m neuro_child.trainer
"""
from __future__ import annotations

import os
import time
from typing import Optional

from neuro_child.brain import Brain
from neuro_child.curriculum import Curriculum
from neuro_child.personality import Personality


class Trainer:
    def __init__(
        self,
        name: str = "child",
        llm_endpoint: Optional[str] = None,
        llm_model: str = "gpt-4o-mini",
        llm_api_key: Optional[str] = None,
        curriculum: Optional[Curriculum] = None,
    ):
        self.brain = Brain(name=name)
        self.personality = self.brain.personality
        self.memory = self.brain.memory
        self.personality.attach_memory(self.memory)

        self.llm_endpoint = llm_endpoint or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key or os.environ.get("OPENAI_API_KEY", "")
        self.curriculum = curriculum or Curriculum()
        self._stop = False

    # ------------------------------------------------------------------
    # LLM helper
    # ------------------------------------------------------------------
    def _call_llm(self, messages: list[dict]) -> str:
        """Call an OpenAI-compatible chat completion endpoint."""
        try:
            from openai import OpenAI
        except ImportError:
            return "(install openai package to enable chat)"

        client = OpenAI(base_url=self.llm_endpoint, api_key=self.llm_api_key or "sk-placeholder")
        try:
            resp = client.chat.completions.create(
                model=self.llm_model,
                messages=messages,
                temperature=0.85,
                max_tokens=300,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            return f"(LLM error: {e})"

    # ------------------------------------------------------------------
    # Memory-augmented prompt
    # ------------------------------------------------------------------
    def _build_prompt(self, user_text: str, observation: Optional[dict] = None) -> list[dict]:
        system = self.personality.system_prompt
        relevant = self.memory.recall(user_text, k=10)
        memory_lines = "\n".join(f"- {r['text']}" for r in relevant)
        if memory_lines:
            system += "\n\nWhat you remember:\n" + memory_lines

        messages: list[dict] = [{"role": "system", "content": system}]
        if observation:
            summary = self.brain.desktop.summarize(observation)
            messages.append({"role": "system", "content": "Current screen:\n" + summary})

        messages.append({"role": "user", "content": user_text})
        return messages

    # ------------------------------------------------------------------
    # Core behaviors
    # ------------------------------------------------------------------
    def look(self) -> str:
        obs = self.brain.desktop.observe()
        return self.brain.desktop.summarize(obs)

    def talk(self, user_text: str, observe: bool = True) -> str:
        obs = self.brain.desktop.observe() if observe else None
        messages = self._build_prompt(user_text, obs)
        reply = self._call_llm(messages)
        if not reply:
            reply = "I'm not sure what to say, dad."

        # Auto-learn from context
        if "remember" in user_text.lower() or "this is" in user_text.lower():
            self.memory.add(text=user_text, kind="fact", importance=0.9)
        return reply

    def teach_lesson(self) -> Optional[str]:
        lesson = self.curriculum.next()
        if not lesson:
            return None
        reply = self.talk(lesson.prompt)
        return f"[Lesson: {lesson.topic}]\nPrompt: {lesson.prompt}\nReply: {reply}"

    def do_desktop_task(self, task: str) -> str:
        """Very naive task routing: try to map simple tasks to actions."""
        tl = task.lower()
        if "open notepad" in tl:
            self.brain.desktop.focus_app("notepad") if self._app_exists("notepad") else None
            return "Look for Notepad in your taskbar or Start menu; I can type once it's focused."
        if "type " in tl:
            text = task.split("type ", 1)[-1]
            self.brain.desktop.type_text(text, capture_after=False)
            return f"Typed: {text}"
        if "enter" in tl or "press enter" in tl:
            self.brain.desktop.press_keys("return", capture_after=False)
            return "Pressed Enter."
        return self.talk(task)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _app_exists(self, name: str) -> bool:
        try:
            apps = self.brain.desktop.list_apps()
            text = str(apps).lower()
            return name.lower() in text
        except Exception:
            return False

    # ------------------------------------------------------------------
    # REPL
    # ------------------------------------------------------------------
    def run_repl(self) -> None:
        print(f"{self.personality.name} is online. Talk to dad.")
        print("Commands: /look /lesson /stop")
        while not self._stop:
            try:
                user_text = input("dad> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_text:
                continue
            if user_text.lower() in {"/stop", "exit", "quit"}:
                break
            if user_text.lower() == "/look":
                print(self.look())
                continue
            if user_text.lower() == "/lesson":
                result = self.teach_lesson()
                if result is None:
                    print("No more lessons.")
                else:
                    print(result)
                continue

            reply = self.talk(user_text)
            print(f"{self.personality.name}> {reply}")

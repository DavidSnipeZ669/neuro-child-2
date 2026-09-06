"""
Simple Game Player — Nova plays basic games with dad.
Currently supports: number guessing, tic-tac-toe.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class GameSession:
    game_type: str
    state: dict = field(default_factory=dict)
    history: List[str] = field(default_factory=list)


class SimpleGamePlayer:
    """Nova's game playing engine for simple games."""

    def __init__(self) -> None:
        self.current: Optional[GameSession] = None

    def start(self, game_type: str) -> str:
        if game_type == "number":
            self.current = GameSession(game_type="number", state={"target": random.randint(1, 100), "attempts": 0})
            return "I'm thinking of a number between 1 and 100. Guess it!"
        elif game_type == "tic-tac-toe":
            self.current = GameSession(game_type="tic-tac-toe", state={"board": [" "] * 9, "turn": "X"})
            return "Let's play tic-tac-toe! You're X, I'm O. Pick a position 1-9."
        return f"I don't know how to play {game_type} yet."

    def move(self, game_type: str, action: str) -> str:
        if self.current is None or self.current.game_type != game_type:
            self.start(game_type)
        try:
            if game_type == "number":
                return self._number_guess(action)
            elif game_type == "tic-tac-toe":
                return self._tic_tac_toe(action)
        except Exception as e:
            return f"Game error: {e}"
        return "Game not started."

    def _number_guess(self, action: str) -> str:
        try:
            guess = int(action.strip())
        except Exception:
            return "Pick a number 1-100"
        target = self.current.state["target"]
        self.current.state["attempts"] += 1
        if guess == target:
            msg = f"You got it in {self.current.state['attempts']} attempts!"
            self.current.history.append(msg)
            self.current = None
            return msg
        elif guess < target:
            return "Higher!"
        else:
            return "Lower!"

    def _tic_tac_toe(self, action: str) -> str:
        try:
            pos = int(action.strip()) - 1
        except Exception:
            return "Pick a position 1-9"
        board = self.current.state["board"]
        if pos < 0 or pos > 8 or board[pos] != " ":
            return "Invalid move, pick 1-9"
        board[pos] = "X"
        # Check win
        wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
        for a,b,c in wins:
            if board[a] == board[b] == board[c] and board[a] != " ":
                self.current = None
                return f"You win! ({board[a]})"
        if " " not in board:
            self.current = None
            return "Draw!"
        # Nova's move
        empty = [i for i in range(9) if board[i] == " "]
        move = random.choice(empty)
        board[move] = "O"
        for a,b,c in wins:
            if board[a] == board[b] == board[c] and board[a] != " ":
                self.current = None
                return f"I win! ({board[a]})"
        if " " not in board:
            self.current = None
            return "Draw!"
        self.current.state["board"] = board
        return f"I played position {move+1}. Board: {''.join(board)}"

    def get_state(self) -> dict:
        if self.current is None:
            return {"active": False}
        return {
            "active": True,
            "game": self.current.game_type,
            "history": self.current.history[-5:],
        }

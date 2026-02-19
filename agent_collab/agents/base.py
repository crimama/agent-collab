"""Base agent interface for Claude Code / Codex CLI wrappers."""
from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentResult:
    agent_name: str
    task: str
    output: str
    error: str
    returncode: int
    duration_s: float

    @property
    def success(self) -> bool:
        return self.returncode == 0

    def display(self, color: bool = True) -> str:
        header = f"[{self.agent_name.upper()}] ({self.duration_s:.1f}s)"
        if color:
            header = _colorize(header, "cyan" if self.agent_name == "claude" else "green")
        separator = "─" * 60
        return f"\n{header}\n{separator}\n{self.output.strip()}\n"


def _colorize(text: str, color: str) -> str:
    codes = {"cyan": "\033[96m", "green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m"}
    reset = "\033[0m"
    return f"{codes.get(color, '')}{text}{reset}"


class BaseAgent:
    name: str

    def run(self, task: str, cwd: str = ".") -> AgentResult:
        raise NotImplementedError

    def run_async(self, task: str, cwd: str = ".", results: list = None) -> threading.Thread:
        def _worker():
            result = self.run(task, cwd)
            if results is not None:
                results.append(result)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return t

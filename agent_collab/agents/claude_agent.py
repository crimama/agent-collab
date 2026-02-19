"""Claude Code CLI wrapper."""
from __future__ import annotations

import subprocess
import time

from .base import AgentResult, BaseAgent


class ClaudeAgent(BaseAgent):
    name = "claude"

    def __init__(self, permission_mode: str = "bypassPermissions", extra_args: list[str] | None = None):
        self.permission_mode = permission_mode
        self.extra_args = extra_args or []

    def run(self, task: str, cwd: str = ".") -> AgentResult:
        cmd = [
            "claude", "--print",
            "--permission-mode", self.permission_mode,
            "--output-format", "text",
            *self.extra_args,
            task,
        ]
        start = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            return AgentResult(
                agent_name=self.name, task=task,
                output=proc.stdout, error=proc.stderr,
                returncode=proc.returncode, duration_s=time.time() - start,
            )
        except FileNotFoundError:
            return AgentResult(
                agent_name=self.name, task=task, output="",
                error="'claude' command not found. Is Claude Code installed?",
                returncode=127, duration_s=time.time() - start,
            )

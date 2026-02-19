"""OpenAI Codex CLI wrapper."""
from __future__ import annotations

import subprocess
import time

from .base import AgentResult, BaseAgent


class CodexAgent(BaseAgent):
    name = "codex"

    def __init__(self, extra_args: list[str] | None = None):
        self.extra_args = extra_args or []

    def run(self, task: str, cwd: str = ".") -> AgentResult:
        # codex exec <prompt> runs non-interactively
        cmd = [
            "codex",
            "exec",
            *self.extra_args,
            task,
        ]
        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd,
            )
            duration = time.time() - start
            # Codex may write output to stderr in some versions
            output = proc.stdout or proc.stderr
            return AgentResult(
                agent_name=self.name,
                task=task,
                output=output,
                error=proc.stderr if proc.stdout else "",
                returncode=proc.returncode,
                duration_s=duration,
            )
        except FileNotFoundError:
            return AgentResult(
                agent_name=self.name,
                task=task,
                output="",
                error="'codex' command not found. Run: npm install -g @openai/codex",
                returncode=127,
                duration_s=time.time() - start,
            )

"""Parallel agent pool — run multiple Claude/Codex agents concurrently."""
from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional

from agent_collab.agents import ClaudeAgent, CodexAgent
from agent_collab.agents.base import AgentResult
from agent_collab.research.state import AgentOutput

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_USE_COLOR = sys.stderr.isatty()


def _c(text: str, *styles: str) -> str:
    if not _USE_COLOR:
        return text
    codes = {
        "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
        "cyan": "\033[96m", "green": "\033[92m", "yellow": "\033[93m",
        "red": "\033[91m",  "magenta": "\033[95m",
    }
    return "".join(codes.get(s, "") for s in styles) + text + codes["reset"]


@dataclass
class PoolTask:
    role: str
    agent: str    # "claude" | "codex"
    prompt: str


class ParallelPool:
    def __init__(self, claude: ClaudeAgent, codex: CodexAgent, cwd: str = ".", step_label: str = ""):
        self.claude = claude
        self.codex = codex
        self.cwd = cwd
        self.step_label = step_label

    def run(
        self,
        tasks: list[PoolTask],
        synthesize: bool = False,
        synthesis_prompt: Optional[str] = None,
    ) -> list[AgentOutput]:
        if not tasks:
            return []

        results: dict[str, tuple] = {}
        lock = threading.Lock()

        def _worker(task: PoolTask):
            agent = self.claude if task.agent == "claude" else self.codex
            res = agent.run(task.prompt, cwd=self.cwd)
            with lock:
                results[task.role] = (task, res)

        threads = [threading.Thread(target=_worker, args=(t,), daemon=True) for t in tasks]

        spin_done = threading.Event()

        def _spin():
            i = 0
            while not spin_done.is_set():
                with lock:
                    n_done = len(results)
                roles = ", ".join(t.role for t in tasks)
                label = _c(self.step_label, "yellow")
                sys.stderr.write(
                    f"\r  {SPINNER[i % len(SPINNER)]}  [{label}] ∥ {roles}  ({n_done}/{len(tasks)} done)"
                )
                sys.stderr.flush()
                time.sleep(0.12)
                i += 1
            sys.stderr.write("\r" + " " * 80 + "\r")
            sys.stderr.flush()

        spin_t = threading.Thread(target=_spin, daemon=True)
        if sys.stderr.isatty():
            spin_t.start()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        spin_done.set()
        spin_t.join(timeout=0.5)

        outputs: list[AgentOutput] = []
        for task in tasks:
            entry = results.get(task.role)
            if entry is None:
                outputs.append(AgentOutput(agent=task.agent, role=task.role,
                                           output="", duration_s=0, success=False, error="No result"))
            else:
                _, res = entry
                outputs.append(AgentOutput(agent=task.agent, role=task.role,
                                           output=res.output, duration_s=res.duration_s,
                                           success=res.success, error=res.error))

        if synthesize and len(outputs) > 1:
            outputs = self._synthesize(outputs, synthesis_prompt)

        return outputs

    def _synthesize(self, outputs: list[AgentOutput], synthesis_prompt: Optional[str]) -> list[AgentOutput]:
        combined = "\n\n".join(f"=== {o.role.upper()} ===\n{o.output}" for o in outputs)
        prompt = synthesis_prompt or (
            f"Synthesize these {len(outputs)} parallel agent outputs into one unified, "
            f"comprehensive response. Keep all unique insights:\n\n{combined}"
        )
        res = self.claude.run(prompt, cwd=self.cwd)
        synthesis = AgentOutput(agent="claude", role="synthesizer",
                                output=res.output, duration_s=res.duration_s,
                                success=res.success, error=res.error)
        return outputs + [synthesis]

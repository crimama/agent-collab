"""
Parallel agent pool — run multiple Claude/Codex agents concurrently,
then optionally synthesize results with a Claude summarizer.
"""
from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

sys.path.insert(0, str(__file__).rsplit("/research", 1)[0])
from agents import ClaudeAgent, CodexAgent
from agents.base import AgentResult
from state import AgentOutput

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_USE_COLOR = sys.stderr.isatty()


def _c(text: str, *styles: str) -> str:
    if not _USE_COLOR:
        return text
    codes = {
        "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
        "cyan": "\033[96m",  "green": "\033[92m", "yellow": "\033[93m",
        "red": "\033[91m",   "magenta": "\033[95m",
    }
    return "".join(codes.get(s, "") for s in styles) + text + codes["reset"]


@dataclass
class PoolTask:
    role: str          # human-readable label e.g. "analyst-1"
    agent: str         # "claude" | "codex"
    prompt: str


class ParallelPool:
    """
    Runs multiple agent tasks in parallel, returns list[AgentOutput].
    Optionally synthesizes results using Claude.
    """

    def __init__(
        self,
        claude: ClaudeAgent,
        codex: CodexAgent,
        cwd: str = ".",
        step_label: str = "",
    ):
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
        """Run all tasks in parallel. If synthesize=True, Claude combines outputs."""
        if not tasks:
            return []

        results: dict[str, AgentResult] = {}
        lock = threading.Lock()
        done_event = threading.Event()

        def _worker(task: PoolTask):
            agent = self.claude if task.agent == "claude" else self.codex
            res = agent.run(task.prompt, cwd=self.cwd)
            with lock:
                results[task.role] = (task, res)

        threads = [threading.Thread(target=_worker, args=(t,), daemon=True) for t in tasks]

        # Start spinner
        spin_done = threading.Event()

        def _spin():
            i = 0
            n_done = 0
            total = len(tasks)
            while not spin_done.is_set():
                with lock:
                    n_done = len(results)
                roles = ", ".join(t.role for t in tasks)
                label = _c(self.step_label, "yellow")
                sys.stderr.write(
                    f"\r  {SPINNER[i % len(SPINNER)]}  [{label}] ∥ {roles}  ({n_done}/{total} done)"
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

        # Build AgentOutput list (in original task order)
        outputs: list[AgentOutput] = []
        for task in tasks:
            task_obj, res = results.get(task.role, (task, None))
            if res is None:
                outputs.append(AgentOutput(
                    agent=task.agent, role=task.role,
                    output="", duration_s=0, success=False, error="No result"
                ))
            else:
                outputs.append(AgentOutput(
                    agent=task.agent, role=task.role,
                    output=res.output, duration_s=res.duration_s,
                    success=res.success, error=res.error,
                ))

        if synthesize and len(outputs) > 1:
            outputs = self._synthesize(outputs, synthesis_prompt)

        return outputs

    def _synthesize(
        self, outputs: list[AgentOutput], synthesis_prompt: Optional[str]
    ) -> list[AgentOutput]:
        """Use Claude to synthesize multiple parallel outputs into one."""
        combined = "\n\n".join(
            f"=== {o.role.upper()} ===\n{o.output}" for o in outputs
        )
        prompt = synthesis_prompt or (
            f"The following are outputs from {len(outputs)} parallel agents working on the same problem. "
            f"Synthesize them into a single, unified, comprehensive response. "
            f"Keep the best insights from each:\n\n{combined}"
        )
        res = self.claude.run(prompt, cwd=self.cwd)
        synthesis = AgentOutput(
            agent="claude", role="synthesizer",
            output=res.output, duration_s=res.duration_s,
            success=res.success, error=res.error,
        )
        return outputs + [synthesis]

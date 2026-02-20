"""Research state management — accumulates knowledge across rounds."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from agent_collab.research.memory import ResearchMemory


@dataclass
class AgentOutput:
    agent: str
    role: str
    output: str
    duration_s: float
    success: bool = True
    error: str = ""


@dataclass
class StepResult:
    step_id: int
    step_name: str
    outputs: list[AgentOutput] = field(default_factory=list)
    synthesized: str = ""
    duration_s: float = 0.0

    def primary_output(self) -> str:
        return self.synthesized or (self.outputs[0].output if self.outputs else "")

    def all_outputs_text(self) -> str:
        return "\n\n".join(f"[{o.agent.upper()} / {o.role}]\n{o.output}" for o in self.outputs)


@dataclass
class RoundResult:
    round_num: int
    started_at: str
    finished_at: str = ""
    steps: dict[str, StepResult] = field(default_factory=dict)
    conclusion: str = ""
    next_hypotheses: list[str] = field(default_factory=list)
    best_metric: Optional[str] = None


class ResearchState:
    def __init__(self, goal: str, session_dir: str = "."):
        self.goal = goal
        self.rounds: list[RoundResult] = []
        self.session_dir = Path(session_dir)
        self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.memory = ResearchMemory.load(Path(session_dir), goal=goal)

    def round_context(self, max_rounds: int = 3) -> str:
        if not self.rounds:
            return "No previous rounds."
        parts = []
        for r in self.rounds[-max_rounds:]:
            parts.append(f"=== Round {r.round_num} ===")
            if r.conclusion:
                parts.append(f"Conclusion: {r.conclusion[:800]}")
            if r.next_hypotheses:
                hyp = "\n".join(f"  - {h}" for h in r.next_hypotheses)
                parts.append(f"Next hypotheses:\n{hyp}")
            if r.best_metric:
                parts.append(f"Best metric: {r.best_metric}")
        return "\n".join(parts)

    def step_context(self, current_round: RoundResult, up_to_step: int) -> str:
        parts = []
        step_order = ["understand", "analyze", "methodology", "experiment", "results", "conclusion"]
        for name in step_order[:up_to_step]:
            res = current_round.steps.get(name)
            if res:
                out = res.primary_output()
                if len(out) > 1500:
                    out = out[:1500] + "\n... [truncated]"
                parts.append(f"[Step: {res.step_name}]\n{out}")
        return "\n\n".join(parts)

    def save(self) -> Path:
        path = self.session_dir / "research_state.json"
        data = {
            "goal": self.goal,
            "created_at": self.created_at,
            "rounds": [asdict(r) for r in self.rounds],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        # Save memory separately
        self.memory.save(self.session_dir)

        return path

    @classmethod
    def load(cls, path: str) -> "ResearchState":
        with open(path) as f:
            data = json.load(f)
        session_dir = Path(path).parent
        state = cls(goal=data["goal"], session_dir=str(session_dir))
        state.created_at = data.get("created_at", "")
        for r_data in data.get("rounds", []):
            steps = {}
            for name, s in r_data.get("steps", {}).items():
                outputs = [AgentOutput(**o) for o in s.get("outputs", [])]
                steps[name] = StepResult(
                    step_id=s["step_id"], step_name=s["step_name"],
                    outputs=outputs, synthesized=s.get("synthesized", ""),
                    duration_s=s.get("duration_s", 0.0),
                )
            rr = RoundResult(
                round_num=r_data["round_num"], started_at=r_data["started_at"],
                finished_at=r_data.get("finished_at", ""), steps=steps,
                conclusion=r_data.get("conclusion", ""),
                next_hypotheses=r_data.get("next_hypotheses", []),
                best_metric=r_data.get("best_metric"),
            )
            state.rounds.append(rr)
        return state

    def markdown_report(self) -> str:
        lines = [f"# AI Research Session\n",
                 f"**Goal:** {self.goal}\n",
                 f"**Started:** {self.created_at}\n",
                 f"**Rounds:** {len(self.rounds)}\n\n"]
        for rr in self.rounds:
            lines.append(f"## Round {rr.round_num}\n")
            for name, step in rr.steps.items():
                lines += [f"### {step.step_name}\n", step.primary_output()[:2000], "\n\n"]
            if rr.conclusion:
                lines += [f"### Conclusion\n", rr.conclusion, "\n\n"]
            if rr.next_hypotheses:
                lines.append("### Next Hypotheses\n")
                for h in rr.next_hypotheses:
                    lines.append(f"- {h}\n")
                lines.append("\n")
        return "".join(lines)

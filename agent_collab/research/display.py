"""Terminal display for AI Research Mode."""
from __future__ import annotations

import sys
from agent_collab.research.state import RoundResult, StepResult

_USE_COLOR = sys.stdout.isatty()

STEP_META = [
    (1, "understand",  "Goal Understanding",          "claude",        "cyan"),
    (2, "analyze",     "Problem Analysis",             "claude×N",      "cyan"),
    (3, "methodology", "Methodology & Implementation", "claude+codex×N","yellow"),
    (4, "experiment",  "Experiment Execution",         "codex×N",       "green"),
    (5, "results",     "Result Analysis",              "claude",        "cyan"),
    (6, "conclusion",  "Conclusion",                   "claude",        "cyan"),
]


def _c(text: str, *styles: str) -> str:
    if not _USE_COLOR:
        return text
    codes = {
        "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
        "cyan": "\033[96m", "green": "\033[92m", "yellow": "\033[93m",
        "red": "\033[91m",  "magenta": "\033[95m",
    }
    return "".join(codes.get(s, "") for s in styles) + text + codes["reset"]


def print_session_header(goal: str, total_rounds: int) -> None:
    w = 72
    print()
    print(_c("╔" + "═" * (w - 2) + "╗", "magenta", "bold"))
    print(_c("║", "magenta") + _c("  AI RESEARCH MODE", "bold") +
          _c(f"  —  {total_rounds} round(s)", "dim") + " " * (w - 22 - len(str(total_rounds))) + _c("║", "magenta"))
    goal_line = f"  Goal: {goal[:w-10]}"
    print(_c("║", "magenta") + goal_line.ljust(w - 2) + _c("║", "magenta"))
    print(_c("╚" + "═" * (w - 2) + "╝", "magenta", "bold"))
    print()


def print_round_header(round_num: int, total_rounds: int) -> None:
    bar = "─" * 60
    print()
    print(_c(bar, "magenta"))
    print(_c(f"  ROUND {round_num}/{total_rounds}", "magenta", "bold"))
    print(_c(bar, "magenta"))
    print()
    for sid, key, name, agents, color in STEP_META:
        print(f"  {_c(f'Step {sid}/6', 'dim')}  {_c(name, color):40}  {_c(agents, 'dim')}")
    print()


def print_step_start(step_id: int, step_name: str, n_agents: int) -> None:
    _, _, _, agents, color = STEP_META[step_id - 1]
    n_str = f" ×{n_agents}" if n_agents > 1 else ""
    print(_c(f"\n▶ Step {step_id}/6  {step_name}", color, "bold") +
          _c(f"  [{agents}{n_str}]", "dim"))


def print_step_result(step: StepResult) -> None:
    out = step.primary_output().strip()
    if not out:
        return
    _, _, _, _, color = STEP_META[step.step_id - 1]
    separator = _c("─" * 60, "dim")
    print(separator)
    lines = out.splitlines()
    for line in lines[:60]:
        print("  " + line)
    if len(lines) > 60:
        print(_c(f"  ... [{len(lines) - 60} more lines]", "dim"))
    agents_used = {o.agent for o in step.outputs}
    print(_c(f"\n  ✓ {step.step_name} complete  ({step.duration_s:.1f}s)", color) +
          _c(f"  [{', '.join(sorted(agents_used))}]", "dim"))
    print()


def print_round_summary(rr: RoundResult) -> None:
    print(_c("\n  ╔══ ROUND SUMMARY ══╗", "magenta", "bold"))
    if rr.best_metric:
        print(_c(f"  Best Metric:  {rr.best_metric}", "green", "bold"))
    if rr.next_hypotheses:
        print(_c("  Next Hypotheses:", "yellow"))
        for h in rr.next_hypotheses[:4]:
            print(f"    • {h}")
    total_t = sum(s.duration_s for s in rr.steps.values())
    print(_c(f"  Total time: {total_t:.0f}s", "dim"))
    print()


def print_final_summary(state) -> None:
    print(_c("\n╔══════════════════════════════════════════════════╗", "magenta", "bold"))
    print(_c("║  RESEARCH SESSION COMPLETE                        ║", "magenta", "bold"))
    print(_c("╚══════════════════════════════════════════════════╝", "magenta", "bold"))
    print(f"\nGoal: {state.goal}\nRounds: {len(state.rounds)}\n")
    for rr in state.rounds:
        metric = _c(rr.best_metric or "—", "green")
        print(f"  Round {rr.round_num}: {metric}")
    print()

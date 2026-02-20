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


def print_session_header(goal: str, total_rounds: int, interactive: bool = False) -> None:
    import textwrap
    w = 72
    print()
    print(_c("╔" + "═" * (w - 2) + "╗", "magenta", "bold"))

    # Title line with round count
    mode_str = " [INTERACTIVE]" if interactive else ""
    title = f"  AI RESEARCH MODE — {total_rounds} Round(s){mode_str}"
    padding = w - 2 - len(f"  AI RESEARCH MODE — {total_rounds} Round(s){mode_str}")
    print(_c("║", "magenta") + _c(title, "bold") + " " * padding + _c("║", "magenta"))

    # Wrap long goal text
    goal_prefix = "  Goal: "
    goal_width = w - 6  # Leave space for "║  " on both sides
    if len(goal) <= goal_width - len(goal_prefix):
        # Short goal - single line
        goal_line = goal_prefix + goal
        print(_c("║", "magenta") + goal_line.ljust(w - 2) + _c("║", "magenta"))
    else:
        # Long goal - wrap into multiple lines
        wrapped = textwrap.wrap(goal, width=goal_width - len(goal_prefix))
        # First line with prefix
        first_line = goal_prefix + wrapped[0]
        print(_c("║", "magenta") + first_line.ljust(w - 2) + _c("║", "magenta"))
        # Remaining lines with indent
        for line in wrapped[1:]:
            indented = "        " + line  # 8 spaces to align with "Goal: "
            print(_c("║", "magenta") + indented.ljust(w - 2) + _c("║", "magenta"))

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


_PREVIEW_LINES = 20


def print_step_result(step: StepResult) -> None:
    out = step.primary_output().strip()
    _, _, _, _, color = STEP_META[step.step_id - 1]
    agents_used = ", ".join(sorted({o.agent for o in step.outputs}))
    t_str = _c(f"{step.duration_s:.1f}s", "dim")

    # ── Step completion header ────────────────────────────────────────────────
    print(_c(f"\n  ✓  {step.step_name}", color, "bold") +
          f"  {t_str}  " + _c(f"[{agents_used}]", "dim"))

    if not out:
        return

    lines = out.splitlines()
    preview = lines[:_PREVIEW_LINES]
    hidden  = len(lines) - _PREVIEW_LINES

    # ── Content preview ───────────────────────────────────────────────────────
    print(_c("  ┄" * 30, "dim"))
    for line in preview:
        display = line[:120] + _c(" …", "dim") if len(line) > 120 else line
        print(f"  {display}")
    if hidden > 0:
        print(_c(f"  ╌╌ +{hidden} more lines (saved to report) ╌╌", "dim"))
    print()

    # ── Critic output (if present) ────────────────────────────────────────────
    critic_out = next((o for o in step.outputs if o.role == "critic"), None)
    if critic_out and critic_out.output.strip():
        print(_c("  ⚠  Critic [CLAUDE]", "red", "bold") +
              _c(f"  {critic_out.duration_s:.1f}s", "dim"))
        print(_c("  ┄" * 30, "dim"))
        clines = critic_out.output.strip().splitlines()
        for line in clines[:_PREVIEW_LINES]:
            display = line[:120] + _c(" …", "dim") if len(line) > 120 else line
            print(f"  {display}")
        if len(clines) > _PREVIEW_LINES:
            print(_c(f"  ╌╌ +{len(clines) - _PREVIEW_LINES} more lines (saved to report) ╌╌", "dim"))
        print()


def print_round_summary(rr: RoundResult) -> None:
    total_t = sum(s.duration_s for s in rr.steps.values())
    print()
    print(_c("  ━" * 35, "magenta"))
    print(_c(f"  ROUND {rr.round_num} COMPLETE", "magenta", "bold") +
          _c(f"  ({total_t:.0f}s total)", "dim"))
    if rr.best_metric:
        print(_c(f"  ★ Best:  {rr.best_metric}", "green", "bold"))
    if rr.next_hypotheses:
        print(_c("  → Next round hypotheses:", "yellow"))
        for h in rr.next_hypotheses[:4]:
            # Trim long hypotheses
            h_display = h[:100] + "…" if len(h) > 100 else h
            print(f"    • {h_display}")
    print(_c("  ━" * 35, "magenta"))
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

#!/usr/bin/env python3
"""
AI Research Mode — Iterative research loop with Claude + Codex

Usage:
  collab research "Improve Pixel AP on MVTec by 5%"
  collab research --rounds 3 "Develop new continual learning strategy"
  collab research --rounds 5 --analysts 2 --implementers 3 --experiments 2 "Goal"
  collab research --resume research_state.json "Continue research"
  collab research --plan-only "Goal"   # Show plan without executing

Round structure:
  Step 1: Goal Understanding        [Claude]
  Step 2: Problem Analysis          [Claude × N analysts, parallel]
  Step 3: Methodology & Impl.       [Claude plans + Codex × N implementers, parallel]
  Step 4: Experiment Execution      [Codex × N experiments, parallel]
  Step 5: Result Analysis           [Claude]
  Step 6: Conclusion                [Claude → feeds next round]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Resolve paths
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

from agents import ClaudeAgent, CodexAgent
from state import AgentOutput, ResearchState, RoundResult
from parallel_pool import ParallelPool, PoolTask
from steps import (
    step1_understand, step2_analyze, step3_methodology,
    step4_experiment, step5_results, step6_conclusion,
)
from display import (
    print_session_header, print_round_header, print_step_start,
    print_step_result, print_round_summary, print_final_summary,
)

import yaml
CONFIG_PATH = _HERE.parent / "config.yaml"


def _c(text: str, *styles: str) -> str:
    if not sys.stdout.isatty():
        return text
    codes = {
        "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
        "cyan": "\033[96m",  "green": "\033[92m", "yellow": "\033[93m",
        "red": "\033[91m",   "magenta": "\033[95m",
    }
    return "".join(codes.get(s, "") for s in styles) + text + codes["reset"]


# ─── Round runner ──────────────────────────────────────────────────────────────
def run_round(
    state: ResearchState,
    round_num: int,
    total_rounds: int,
    claude: ClaudeAgent,
    codex: CodexAgent,
    cwd: str,
    cfg: dict,
) -> RoundResult:
    n_analysts     = cfg["n_analysts"]
    n_implementers = cfg["n_implementers"]
    n_experiments  = cfg["n_experiments"]

    rr = RoundResult(
        round_num=round_num,
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    # Shared pools (one for claude, one for codex)
    claude_pool = ParallelPool(claude, codex, cwd=cwd, step_label=f"R{round_num}/CLAUDE")
    codex_pool  = ParallelPool(claude, codex, cwd=cwd, step_label=f"R{round_num}/CODEX")

    # ── Step 1: Goal Understanding ────────────────────────────────────────────
    print_step_start(1, "Goal Understanding", 1)
    s1 = step1_understand(state, rr, claude, cwd)
    rr.steps["understand"] = s1
    print_step_result(s1)
    state.save()

    # ── Step 2: Problem Analysis (parallel analysts) ───────────────────────────
    print_step_start(2, "Problem Analysis", n_analysts)
    s2 = step2_analyze(state, rr, claude_pool, n_analysts=n_analysts)
    rr.steps["analyze"] = s2
    print_step_result(s2)
    state.save()

    # ── Step 3: Methodology + Implementation ───────────────────────────────────
    print_step_start(3, "Methodology & Implementation", n_implementers + 1)
    s3 = step3_methodology(state, rr, claude, codex_pool,
                           n_implementers=n_implementers, cwd=cwd)
    rr.steps["methodology"] = s3
    print_step_result(s3)
    state.save()

    # ── Step 4: Experiment Execution (parallel experiments) ───────────────────
    print_step_start(4, "Experiment Execution", n_experiments)
    s4 = step4_experiment(state, rr, codex_pool, n_experiments=n_experiments, cwd=cwd)
    rr.steps["experiment"] = s4
    print_step_result(s4)
    state.save()

    # ── Step 5: Result Analysis ────────────────────────────────────────────────
    print_step_start(5, "Result Analysis", 1)
    s5 = step5_results(state, rr, claude, cwd)
    rr.steps["results"] = s5
    print_step_result(s5)
    state.save()

    # ── Step 6: Conclusion ─────────────────────────────────────────────────────
    print_step_start(6, "Conclusion", 1)
    s6 = step6_conclusion(state, rr, total_rounds, claude, cwd)
    rr.steps["conclusion"] = s6
    print_step_result(s6)

    rr.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
    state.rounds.append(rr)
    state.save()
    return rr


# ─── Session runner ────────────────────────────────────────────────────────────
def run_research_session(
    goal: str,
    total_rounds: int,
    claude: ClaudeAgent,
    codex: CodexAgent,
    cwd: str,
    cfg: dict,
    resume_path: str | None = None,
    plan_only: bool = False,
) -> None:
    # Init or resume state
    if resume_path and Path(resume_path).exists():
        state = ResearchState.load(resume_path)
        print(_c(f"Resuming session from {resume_path} (round {len(state.rounds)+1})", "yellow"))
    else:
        state = ResearchState(goal=goal, session_dir=cwd)

    print_session_header(goal, total_rounds)

    if plan_only:
        print(_c("Plan-only mode: showing round structure without executing.\n", "dim"))
        for r in range(1, total_rounds + 1):
            print_round_header(r, total_rounds)
        return

    # Run rounds
    direction = "continue"
    for round_num in range(len(state.rounds) + 1, total_rounds + 1):
        print_round_header(round_num, total_rounds)
        rr = run_round(state, round_num, total_rounds, claude, codex, cwd, cfg)
        print_round_summary(rr)

        # Check if research says "done" or "pivot"
        direction = _extract_direction(rr)
        if direction == "done":
            print(_c(f"\n✓ Research completed early at round {round_num} (goal achieved).", "green", "bold"))
            break
        if direction == "pivot":
            print(_c(f"\n↻ Pivoting research direction at round {round_num}.", "yellow", "bold"))
            # Continue but with a note in state

    # Save final report
    report_path = Path(cwd) / f"research_report_{time.strftime('%Y%m%d_%H%M%S')}.md"
    report_path.write_text(state.markdown_report())

    print_final_summary(state)
    print(_c(f"Report saved → {report_path}", "dim"))
    print(_c(f"State saved  → {state.save()}", "dim"))


def _extract_direction(rr: RoundResult) -> str:
    # Already parsed by step6
    if not rr.conclusion:
        return "continue"
    low = rr.conclusion.lower()
    if '"direction": "done"' in low or "'direction': 'done'" in low:
        return "done"
    if '"direction": "pivot"' in low or "'direction': 'pivot'" in low:
        return "pivot"
    return "continue"


# ─── CLI ───────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Research Mode — iterative Claude+Codex research loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("goal", nargs="*", help="Research goal or objective")
    parser.add_argument("--rounds",        type=int, default=3,  help="Number of research rounds (default: 3)")
    parser.add_argument("--analysts",      type=int, default=2,  help="Parallel Claude analysts in Step 2 (default: 2)")
    parser.add_argument("--implementers",  type=int, default=2,  help="Parallel Codex implementers in Step 3 (default: 2)")
    parser.add_argument("--experiments",   type=int, default=2,  help="Parallel Codex experiments in Step 4 (default: 2)")
    parser.add_argument("--cwd",           default=".",          help="Working directory (default: current)")
    parser.add_argument("--resume",        default=None,         help="Resume from research_state.json path")
    parser.add_argument("--plan-only",     action="store_true",  help="Show plan without executing")

    args = parser.parse_args()

    if not args.goal and not args.resume:
        parser.print_help()
        sys.exit(1)

    goal = " ".join(args.goal) if args.goal else ""
    if args.resume and not goal:
        state = ResearchState.load(args.resume)
        goal = state.goal

    cfg_data = yaml.safe_load(open(CONFIG_PATH))
    claude_cfg = cfg_data["agents"]["claude"]
    codex_cfg  = cfg_data["agents"]["codex"]

    claude = ClaudeAgent(
        permission_mode=claude_cfg.get("permission_mode", "bypassPermissions"),
        extra_args=claude_cfg.get("extra_args", []),
    )
    codex = CodexAgent(extra_args=codex_cfg.get("extra_args", []))

    cfg = {
        "n_analysts":     args.analysts,
        "n_implementers": args.implementers,
        "n_experiments":  args.experiments,
    }

    run_research_session(
        goal=goal,
        total_rounds=args.rounds,
        claude=claude,
        codex=codex,
        cwd=os.path.abspath(args.cwd),
        cfg=cfg,
        resume_path=args.resume,
        plan_only=args.plan_only,
    )


if __name__ == "__main__":
    main()

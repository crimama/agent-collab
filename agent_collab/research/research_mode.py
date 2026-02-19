"""AI Research Mode — iterative research loop entry point."""
from __future__ import annotations

import argparse
import os
import sys
import time
import threading
from pathlib import Path

import yaml

from agent_collab.agents import ClaudeAgent, CodexAgent
from agent_collab.research.state import ResearchState, RoundResult
from agent_collab.research.parallel_pool import ParallelPool
from agent_collab.research.steps import (
    step1_understand, step2_analyze, step3_methodology,
    step4_experiment, step5_results, step6_conclusion,
)
from agent_collab.research.display import (
    print_session_header, print_round_header, print_step_start,
    print_step_result, print_round_summary, print_final_summary,
)

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_USE_COLOR = sys.stdout.isatty()


def _c(text: str, *styles: str) -> str:
    if not _USE_COLOR:
        return text
    codes = {"reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
             "cyan": "\033[96m", "green": "\033[92m", "yellow": "\033[93m",
             "red": "\033[91m",  "magenta": "\033[95m"}
    return "".join(codes.get(s, "") for s in styles) + text + codes["reset"]


def run_round(state, round_num, total_rounds, claude, codex, cwd, cfg) -> RoundResult:
    rr = RoundResult(round_num=round_num, started_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    claude_pool = ParallelPool(claude, codex, cwd=cwd, step_label=f"R{round_num}/CLAUDE")
    codex_pool  = ParallelPool(claude, codex, cwd=cwd, step_label=f"R{round_num}/CODEX")

    print_step_start(1, "Goal Understanding", 1)
    rr.steps["understand"] = s1 = step1_understand(state, rr, claude, cwd)
    print_step_result(s1); state.save()

    print_step_start(2, "Problem Analysis", cfg["n_analysts"])
    rr.steps["analyze"] = s2 = step2_analyze(state, rr, claude_pool, n_analysts=cfg["n_analysts"])
    print_step_result(s2); state.save()

    print_step_start(3, "Methodology & Implementation", cfg["n_implementers"] + 1)
    rr.steps["methodology"] = s3 = step3_methodology(
        state, rr, claude, codex_pool, n_implementers=cfg["n_implementers"], cwd=cwd)
    print_step_result(s3); state.save()

    print_step_start(4, "Experiment Execution", cfg["n_experiments"])
    rr.steps["experiment"] = s4 = step4_experiment(
        state, rr, codex_pool, n_experiments=cfg["n_experiments"], cwd=cwd)
    print_step_result(s4); state.save()

    print_step_start(5, "Result Analysis", 1)
    rr.steps["results"] = s5 = step5_results(state, rr, claude, cwd)
    print_step_result(s5); state.save()

    print_step_start(6, "Conclusion", 1)
    rr.steps["conclusion"] = s6 = step6_conclusion(state, rr, total_rounds, claude, cwd)
    print_step_result(s6)

    rr.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
    state.rounds.append(rr)
    state.save()
    return rr


def run_research_session(goal, total_rounds, claude, codex, cwd, cfg,
                         resume_path=None, plan_only=False) -> None:
    if resume_path and Path(resume_path).exists():
        state = ResearchState.load(resume_path)
        print(_c(f"Resuming from {resume_path} (round {len(state.rounds)+1})", "yellow"))
    else:
        state = ResearchState(goal=goal, session_dir=cwd)

    print_session_header(goal, total_rounds)

    if plan_only:
        print(_c("Plan-only mode: showing structure without executing.\n", "dim"))
        for r in range(1, total_rounds + 1):
            print_round_header(r, total_rounds)
        return

    for round_num in range(len(state.rounds) + 1, total_rounds + 1):
        print_round_header(round_num, total_rounds)
        rr = run_round(state, round_num, total_rounds, claude, codex, cwd, cfg)
        print_round_summary(rr)

        direction = rr.conclusion.lower() if rr.conclusion else ""
        if '"direction": "done"' in direction:
            print(_c(f"\n✓ Research completed early at round {round_num}.", "green", "bold"))
            break
        if '"direction": "pivot"' in direction:
            print(_c(f"\n↻ Pivoting research direction at round {round_num}.", "yellow", "bold"))

    report_path = Path(cwd) / f"research_report_{time.strftime('%Y%m%d_%H%M%S')}.md"
    report_path.write_text(state.markdown_report())
    print_final_summary(state)
    print(_c(f"Report → {report_path}", "dim"))
    print(_c(f"State  → {state.save()}", "dim"))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="collab research",
        description="AI Research Mode — iterative Claude+Codex research loop",
    )
    parser.add_argument("goal", nargs="*")
    parser.add_argument("--rounds",       type=int, default=3)
    parser.add_argument("--analysts",     type=int, default=2)
    parser.add_argument("--implementers", type=int, default=2)
    parser.add_argument("--experiments",  type=int, default=2)
    parser.add_argument("--cwd",          default=".")
    parser.add_argument("--resume",       default=None)
    parser.add_argument("--plan-only",    action="store_true")

    args = parser.parse_args(argv)

    if not args.goal and not args.resume:
        parser.print_help()
        sys.exit(1)

    goal = " ".join(args.goal) if args.goal else ResearchState.load(args.resume).goal
    cfg_data = yaml.safe_load(open(CONFIG_PATH))
    claude = ClaudeAgent(
        permission_mode=cfg_data["agents"]["claude"].get("permission_mode", "bypassPermissions"),
        extra_args=cfg_data["agents"]["claude"].get("extra_args", []),
    )
    codex = CodexAgent(extra_args=cfg_data["agents"]["codex"].get("extra_args", []))

    run_research_session(
        goal=goal, total_rounds=args.rounds, claude=claude, codex=codex,
        cwd=os.path.abspath(args.cwd),
        cfg={"n_analysts": args.analysts, "n_implementers": args.implementers,
             "n_experiments": args.experiments},
        resume_path=args.resume, plan_only=args.plan_only,
    )


if __name__ == "__main__":
    main()

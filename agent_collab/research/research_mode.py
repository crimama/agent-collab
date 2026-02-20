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
from agent_collab.file_ref import expand_file_refs
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
    state.save()  # This also saves memory

    # Print memory stats
    n_insights = len([e for e in state.memory.entries if e.type in ("insight", "success")])
    n_mistakes = len([e for e in state.memory.entries if e.type in ("mistake", "failure")])
    if n_insights or n_mistakes:
        print(_c(f"\n  📚 Research Memory: {n_insights} insights, {n_mistakes} mistakes recorded", "dim"))

    return rr


def run_research_session(goal, total_rounds, claude, codex, cwd, cfg,
                         resume_path=None, plan_only=False, interactive=False) -> None:
    from agent_collab.session_store import new_research_session

    # Expand any /file references in the goal
    goal, attached = expand_file_refs(goal, cwd)
    if attached:
        import os
        names = [os.path.basename(p) for p in attached]
        print(_c(f"  📎 {len(attached)} file(s) attached: {', '.join(names)}", "dim"))

    if resume_path and Path(resume_path).exists():
        state = ResearchState.load(resume_path)
        print(_c(f"Resuming from {resume_path} (round {len(state.rounds)+1})", "yellow"))
        collab_session = None  # already registered on first run
    else:
        state = ResearchState(goal=goal, session_dir=cwd)
        state_path = str(Path(cwd) / "research_state.json")
        collab_session = new_research_session(goal, cwd, total_rounds, state_path)
        print(_c(f"Session saved → {collab_session.id}", "dim"))

    print_session_header(goal, total_rounds, interactive=interactive)

    if plan_only:
        print(_c("Plan-only mode: showing structure without executing.\n", "dim"))
        for r in range(1, total_rounds + 1):
            print_round_header(r, total_rounds)
        return

    try:
        for round_num in range(len(state.rounds) + 1, total_rounds + 1):
            print_round_header(round_num, total_rounds)
            rr = run_round(state, round_num, total_rounds, claude, codex, cwd, cfg)
            print_round_summary(rr)

            # Update session progress
            if collab_session:
                collab_session.current_round = round_num
                collab_session.research_state_path = str(state.save())
                collab_session.save()

            # Check auto-termination
            direction = rr.conclusion.lower() if rr.conclusion else ""
            if '"direction": "done"' in direction:
                print(_c(f"\n✓ Research completed early at round {round_num}.", "green", "bold"))
                break
            if '"direction": "pivot"' in direction:
                print(_c(f"\n↻ Pivoting research direction at round {round_num}.", "yellow", "bold"))

            # Interactive confirmation before next round
            if interactive and round_num < total_rounds:
                print()
                print(_c("─" * 70, "dim"))
                print(_c(f"  Round {round_num}/{total_rounds} completed.", "cyan", "bold"))
                print(_c(f"  {total_rounds - round_num} round(s) remaining.", "dim"))
                print()

                try:
                    response = input(_c("  Continue to next round? [Y/n/q]: ", "yellow", "bold")).strip().lower()
                    if response in ("n", "no", "q", "quit", "exit"):
                        print(_c(f"\n  ⏸  Research paused after round {round_num}.", "yellow", "bold"))
                        print(_c(f"  Resume with: collab research --resume research_state.json", "dim"))
                        break
                    # Any other input (including empty/Enter) continues
                except (EOFError, KeyboardInterrupt):
                    print()
                    print(_c(f"\n  ⏸  Research paused after round {round_num}.", "yellow", "bold"))
                    break
    except KeyboardInterrupt:
        print(_c("\n\n  ⚠️  Research cancelled by user", "yellow", "bold"))
        print(_c(f"  Progress saved at round {len(state.rounds)}", "dim"))
        print()
        if collab_session:
            collab_session.save()
        return

    if collab_session:
        collab_session.mark_completed()

    report_path = Path(cwd) / f"research_report_{time.strftime('%Y%m%d_%H%M%S')}.md"
    report_path.write_text(state.markdown_report())
    print_final_summary(state)

    # Save memory and show location
    memory_path = state.memory.save(Path(cwd))
    print(_c(f"\nReport    → {report_path}", "dim"))
    print(_c(f"Learnings → {memory_path}", "dim"))
    print(_c(f"State     → {state.save()}", "dim"))

    # Print memory summary
    n_total = len(state.memory.entries)
    n_insights = len([e for e in state.memory.entries if e.type in ("insight", "success")])
    n_mistakes = len([e for e in state.memory.entries if e.type in ("mistake", "failure")])
    print(_c(f"\n📚 Research Memory Summary:", "cyan", "bold"))
    print(_c(f"  Total entries: {n_total}", "dim"))
    print(_c(f"  💡 Insights/Successes: {n_insights}", "green"))
    print(_c(f"  ❌ Mistakes/Failures: {n_mistakes}", "yellow"))
    if state.memory.patterns:
        print(_c(f"  🔍 Patterns identified: {len(state.memory.patterns)}", "dim"))


def show_research_session_picker() -> Optional[str]:
    """
    Show interactive picker for research sessions.
    Returns: research_state_path or None if cancelled.
    """
    from agent_collab.session_store import list_research_sessions

    sessions = list_research_sessions(limit=15)

    if not sessions:
        print(_c("No research sessions found.", "yellow"))
        print(_c("Start a new research session with: collab research \"<goal>\"", "dim"))
        return None

    print()
    print(_c("╔════════════════════════════════════════════════════════════════╗", "cyan"))
    print(_c("║  Recent Research Sessions                                      ║", "cyan", "bold"))
    print(_c("╚════════════════════════════════════════════════════════════════╝", "cyan"))
    print()

    # Display sessions
    print(f"  {'#':>3}  {'Updated':16}  {'Progress':12}  {'Goal'}")
    print("  " + "─" * 80)

    for i, s in enumerate(sessions, 1):
        # Format fields
        num = _c(f"{i:>3}", "cyan", "bold")
        updated = s.updated_at.split()[0]  # Just date
        progress = s.progress_label()

        # Status color
        if s.status == "completed":
            status_color = "green"
        elif s.status == "in_progress":
            status_color = "yellow"
        else:
            status_color = "dim"

        progress_colored = _c(f"{progress:12}", status_color)

        # Truncate long goals
        goal = s.goal[:50] + "..." if len(s.goal) > 50 else s.goal

        print(f"  {num}  {updated:16}  {progress_colored}  {goal}")

    print()
    print(_c("  💡 Tip: Enter number to resume, or 'q' to cancel", "dim"))
    print()

    # Get user selection
    try:
        choice = input(_c("Select session: ", "cyan", "bold")).strip()

        if choice.lower() in ("q", "quit", "exit", ""):
            return None

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                selected = sessions[idx]

                # Validate research_state_path exists
                if not selected.research_state_path:
                    print(_c(f"  ⚠️  No research state path found for this session", "yellow"))
                    return None

                state_path = Path(selected.research_state_path)
                if not state_path.exists():
                    print(_c(f"  ⚠️  Research state file not found: {state_path}", "yellow"))
                    print(_c(f"  The session may have been moved or deleted.", "dim"))
                    return None

                print(_c(f"\n  ✓ Resuming: {selected.goal}", "green"))
                print(_c(f"  📍 {selected.research_state_path}", "dim"))
                print(_c(f"  🔄 Progress: {selected.progress_label()}", "dim"))
                print()
                return selected.research_state_path
            else:
                print(_c(f"  ⚠️  Invalid selection: {choice}", "red"))
                return None
        except ValueError:
            print(_c(f"  ⚠️  Invalid input: {choice}", "red"))
            return None

    except (EOFError, KeyboardInterrupt):
        print()
        return None


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="collab research",
        description="AI Research Mode — iterative Claude+Codex research loop",
        epilog="""
Examples:
  # Start new research (3 rounds by default)
  collab research "Improve accuracy by 5%%"

  # Specify number of rounds
  collab research "Optimize performance" --rounds 5

  # Interactive mode (confirm after each round)
  collab research "Complex task" --rounds 10 -i

  # Resume from picker (shows list of recent sessions)
  collab research --resume

  # Resume specific session
  collab research --resume /path/to/research_state.json

  # Resume with interactive mode
  collab research --resume -i
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("goal", nargs="*")
    parser.add_argument("--rounds",       type=int, default=3,
                       help="Maximum number of research rounds (default: 3)")
    parser.add_argument("--analysts",     type=int, default=2)
    parser.add_argument("--implementers", type=int, default=2)
    parser.add_argument("--experiments",  type=int, default=2)
    parser.add_argument("--cwd",          default=".")
    parser.add_argument("--resume",       default=None, nargs="?", const="PICKER",
                       help="Resume a research session (shows picker if no path given)")
    parser.add_argument("--plan-only",    action="store_true")
    parser.add_argument("--interactive",  "-i", action="store_true",
                       help="Ask for confirmation after each round")

    args = parser.parse_args(argv)

    # Handle --resume without path → show picker
    if args.resume == "PICKER":
        resume_path = show_research_session_picker()
        if not resume_path:
            print(_c("Resume cancelled.", "dim"))
            sys.exit(0)
        args.resume = resume_path

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
        interactive=args.interactive,
    )


if __name__ == "__main__":
    main()

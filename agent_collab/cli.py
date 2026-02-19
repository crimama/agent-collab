#!/usr/bin/env python3
"""
collab — Claude Code + Codex CLI orchestrator

Usage:
  collab "Build a FastAPI REST API with JWT authentication"
  collab --claude "Explain the architecture"
  collab --codex  "Generate CRUD boilerplate"
  collab --parallel "Compare approaches for OAuth2"
  collab --plan-only "Design a microservice system"
  collab -i
  collab research "Improve Pixel AP on MVTec by 5%"
  collab research --rounds 5 --analysts 2 --implementers 3 --experiments 2 "Goal"
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

import yaml

from agent_collab.agents import ClaudeAgent, CodexAgent
from agent_collab.agents.base import AgentResult

CONFIG_PATH = Path(__file__).parent / "config.yaml"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_USE_COLOR = sys.stdout.isatty()


def _c(text: str, *styles: str) -> str:
    if not _USE_COLOR:
        return text
    codes = {
        "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
        "cyan": "\033[96m", "green": "\033[92m", "yellow": "\033[93m",
        "red": "\033[91m",  "magenta": "\033[95m",
    }
    return "".join(codes.get(s, "") for s in styles) + text + codes["reset"]


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def build_agents(cfg: dict) -> tuple[ClaudeAgent, CodexAgent]:
    cc = cfg["agents"]["claude"]
    cx = cfg["agents"]["codex"]
    return (
        ClaudeAgent(permission_mode=cc.get("permission_mode", "bypassPermissions"),
                    extra_args=cc.get("extra_args", [])),
        CodexAgent(extra_args=cx.get("extra_args", [])),
    )


# ─── Single / Parallel agent modes ───────────────────────────────────────────
def run_single(agent, task: str, cwd: str) -> None:
    done = threading.Event()
    label = _c(agent.name.upper(), "cyan" if agent.name == "claude" else "green", "bold")

    def _spin():
        i = 0
        while not done.is_set():
            sys.stderr.write(f"\r{SPINNER[i % len(SPINNER)]}  [{label}] thinking...")
            sys.stderr.flush()
            time.sleep(0.1)
            i += 1
        sys.stderr.write("\r" + " " * 50 + "\r")
        sys.stderr.flush()

    spin_t = threading.Thread(target=_spin, daemon=True)
    if sys.stderr.isatty():
        spin_t.start()

    result: AgentResult = agent.run(task, cwd=cwd)
    done.set()
    spin_t.join(timeout=0.5)

    if not result.success:
        print(_c(f"[{agent.name.upper()} ERROR]", "red", "bold"))
        print(result.error)
        sys.exit(1)
    print(result.display(color=_USE_COLOR))


def run_parallel(claude: ClaudeAgent, codex: CodexAgent, task: str, cwd: str) -> None:
    results: list[AgentResult] = []
    threads = [claude.run_async(task, cwd=cwd, results=results),
               codex.run_async(task, cwd=cwd, results=results)]
    done = threading.Event()

    def _spin():
        i = 0
        while not done.is_set():
            sys.stderr.write(
                f"\r{SPINNER[i % len(SPINNER)]}  Running Claude + Codex in parallel... ({len(results)}/2 done)"
            )
            sys.stderr.flush()
            time.sleep(0.1)
            i += 1
        sys.stderr.write("\r" + " " * 70 + "\r")
        sys.stderr.flush()

    spin_t = threading.Thread(target=_spin, daemon=True)
    if sys.stderr.isatty():
        spin_t.start()
    for t in threads:
        t.join(timeout=120)
    done.set()
    spin_t.join(timeout=0.5)
    results.sort(key=lambda r: 0 if r.agent_name == "claude" else 1)
    for r in results:
        print(r.display(color=_USE_COLOR))


# ─── Goal-driven planning mode ────────────────────────────────────────────────
def run_goal(goal: str, cwd: str, claude: ClaudeAgent, codex: CodexAgent, plan_only: bool = False) -> None:
    from agent_collab.planner import generate_plan
    from agent_collab.plan_ui import edit_plan, print_plan
    from agent_collab.executor import execute_plan

    print(_c(f"\n⚙  Generating plan for: {goal}", "bold"))
    done = threading.Event()

    def _spin():
        i = 0
        while not done.is_set():
            sys.stderr.write(f"\r{SPINNER[i % len(SPINNER)]}  Planning...")
            sys.stderr.flush()
            time.sleep(0.1)
            i += 1
        sys.stderr.write("\r" + " " * 30 + "\r")
        sys.stderr.flush()

    spin_t = threading.Thread(target=_spin, daemon=True)
    if sys.stderr.isatty():
        spin_t.start()
    try:
        plan = generate_plan(goal, cwd)
    except Exception as e:
        done.set()
        print(_c(f"\nPlanning failed: {e}", "red"))
        sys.exit(1)
    finally:
        done.set()
        spin_t.join(timeout=0.5)

    final_plan = edit_plan(plan)
    if final_plan is None:
        print(_c("Cancelled.", "dim"))
        return
    if plan_only:
        print_plan(final_plan, verbose=True)
        return
    execute_plan(final_plan, cwd=cwd, claude=claude, codex=codex)


# ─── Interactive REPL ─────────────────────────────────────────────────────────
def interactive_loop(claude: ClaudeAgent, codex: CodexAgent, cwd: str) -> None:
    print(_c("╭───────────────────────────────────────────╮", "cyan"))
    print(_c("│  agent-collab  (Claude ↔ Codex CLI)       │", "cyan", "bold"))
    print(_c("╰───────────────────────────────────────────╯", "cyan"))
    print()
    print("  " + _c("(no prefix)",    "yellow") + "  Goal → Plan → Execute")
    print("  " + _c("/claude <task>", "yellow") + "  Force Claude Code")
    print("  " + _c("/codex <task>",  "yellow") + "  Force Codex CLI")
    print("  " + _c("/parallel <t>",  "yellow") + "  Run both simultaneously")
    print("  " + _c("/plan <goal>",   "yellow") + "  Generate plan without executing")
    print("  " + _c("/quit",          "yellow") + "  Exit")
    print()

    while True:
        try:
            raw = input(_c("▶ ", "magenta", "bold")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw or raw in ("/quit", "/exit", "quit", "exit"):
            break
        if raw.startswith("/claude "):
            run_single(claude, raw[8:].strip(), cwd)
        elif raw.startswith("/codex "):
            run_single(codex, raw[7:].strip(), cwd)
        elif raw.startswith("/parallel "):
            run_parallel(claude, codex, raw[10:].strip(), cwd)
        elif raw.startswith("/plan "):
            run_goal(raw[6:].strip(), cwd, claude, codex, plan_only=True)
        else:
            run_goal(raw, cwd, claude, codex)


# ─── Research subcommand ──────────────────────────────────────────────────────
def run_research(argv: list[str]) -> None:
    from agent_collab.research.research_mode import main as research_main
    research_main(argv)


# ─── Main entry point ─────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    # Route 'research' subcommand before argparse
    if argv and argv[0] == "research":
        run_research(argv[1:])
        return

    parser = argparse.ArgumentParser(
        prog="collab",
        description="Claude Code + Codex CLI orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("goal", nargs="*", help="Development goal or task")
    parser.add_argument("--claude",      action="store_true", help="Force Claude Code")
    parser.add_argument("--codex",       action="store_true", help="Force Codex CLI")
    parser.add_argument("--parallel",    action="store_true", help="Run both agents simultaneously")
    parser.add_argument("--plan-only",   action="store_true", help="Generate plan without executing")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive REPL mode")
    parser.add_argument("--cwd",         default=".", help="Working directory for agents")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args(argv)
    cfg = load_config()
    claude, codex = build_agents(cfg)
    cwd = os.path.abspath(args.cwd)

    if args.interactive or not args.goal:
        interactive_loop(claude, codex, cwd)
        return

    goal = " ".join(args.goal)

    if args.claude:
        run_single(claude, goal, cwd)
    elif args.codex:
        run_single(codex, goal, cwd)
    elif args.parallel:
        run_parallel(claude, codex, goal, cwd)
    else:
        run_goal(goal, cwd, claude, codex, plan_only=args.plan_only)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
agent-collab: Claude Code + Codex CLI goal-driven orchestrator

Usage:
  collab "Build a FastAPI REST API with JWT authentication"
  collab --plan-only "Create a data pipeline from CSV to PostgreSQL"
  collab --claude "Task to force on Claude Code"
  collab --codex  "Task to force on Codex CLI"
  collab --parallel "Task to run on both agents simultaneously"
  collab -i                           # interactive REPL mode
  collab --cwd /my/project "..."      # set working directory
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from agents import ClaudeAgent, CodexAgent
from agents.base import AgentResult
from executor import execute_plan
from plan_ui import edit_plan, print_plan
from planner import generate_plan

# ─── Config ───────────────────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config.yaml"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_USE_COLOR = sys.stdout.isatty()


def _c(text: str, *styles: str) -> str:
    if not _USE_COLOR:
        return text
    codes = {
        "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
        "cyan": "\033[96m",  "green": "\033[92m", "yellow": "\033[93m",
        "red": "\033[91m",   "magenta": "\033[95m",
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


# ─── Single-agent (no planning) mode ─────────────────────────────────────────
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


def run_parallel(claude: ClaudeAgent, codex: CodexAgent, task: str, cwd: str, timeout: int = 120) -> None:
    results: list[AgentResult] = []
    threads = [
        claude.run_async(task, cwd=cwd, results=results),
        codex.run_async(task, cwd=cwd, results=results),
    ]
    done = threading.Event()

    def _spin():
        i = 0
        while not done.is_set():
            n = len(results)
            sys.stderr.write(f"\r{SPINNER[i % len(SPINNER)]}  Running Claude + Codex in parallel... ({n}/2 done)")
            sys.stderr.flush()
            time.sleep(0.1)
            i += 1
        sys.stderr.write("\r" + " " * 70 + "\r")
        sys.stderr.flush()

    spin_t = threading.Thread(target=_spin, daemon=True)
    if sys.stderr.isatty():
        spin_t.start()

    for t in threads:
        t.join(timeout=timeout)
    done.set()
    spin_t.join(timeout=0.5)

    results.sort(key=lambda r: 0 if r.agent_name == "claude" else 1)
    for r in results:
        print(r.display(color=_USE_COLOR))


# ─── Goal-driven planning mode ────────────────────────────────────────────────
def run_goal(goal: str, cwd: str, claude: ClaudeAgent, codex: CodexAgent, plan_only: bool = False) -> None:
    # 1. Generate plan
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

    # 2. Let user review / edit
    final_plan = edit_plan(plan)
    if final_plan is None:
        print(_c("Cancelled.", "dim"))
        return

    if plan_only:
        print_plan(final_plan, verbose=True)
        return

    # 3. Execute
    execute_plan(final_plan, cwd=cwd, claude=claude, codex=codex)


# ─── Interactive REPL ─────────────────────────────────────────────────────────
def interactive_loop(claude: ClaudeAgent, codex: CodexAgent, cwd: str) -> None:
    print(_c("╭───────────────────────────────────────────╮", "cyan"))
    print(_c("│  agent-collab  (Claude ↔ Codex CLI)       │", "cyan", "bold"))
    print(_c("│  Type a goal or use a command prefix       │", "dim"))
    print(_c("╰───────────────────────────────────────────╯", "cyan"))
    print()
    print(_c("Prefixes:", "bold"))
    print("  " + _c("(no prefix)",   "yellow") + "  Generate plan → review → execute")
    print("  " + _c("/claude <task>","yellow") + "  Force Claude Code (no planning)")
    print("  " + _c("/codex <task>", "yellow") + "  Force Codex CLI  (no planning)")
    print("  " + _c("/parallel <t>", "yellow") + "  Run both agents simultaneously")
    print("  " + _c("/plan <goal>",  "yellow") + "  Generate & show plan without executing")
    print("  " + _c("/quit",         "yellow") + "  Exit")
    print()

    while True:
        try:
            raw = input(_c("▶ ", "magenta", "bold")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue
        if raw in ("/quit", "/exit", "quit", "exit"):
            break

        # Parse prefix
        if raw.startswith("/claude "):
            run_single(claude, raw[8:].strip(), cwd)
        elif raw.startswith("/codex "):
            run_single(codex, raw[7:].strip(), cwd)
        elif raw.startswith("/parallel "):
            run_parallel(claude, codex, raw[10:].strip(), cwd)
        elif raw.startswith("/plan "):
            run_goal(raw[6:].strip(), cwd, claude, codex, plan_only=True)
        else:
            # Default: full goal → plan → execute
            run_goal(raw, cwd, claude, codex)


# ─── Entry point ──────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Claude Code + Codex CLI goal-driven orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("goal", nargs="*", help="Development goal or task")
    parser.add_argument("--claude",     action="store_true", help="Force Claude Code (skip planning)")
    parser.add_argument("--codex",      action="store_true", help="Force Codex CLI  (skip planning)")
    parser.add_argument("--parallel",   action="store_true", help="Run both agents simultaneously")
    parser.add_argument("--plan-only",  action="store_true", help="Generate & display plan, do not execute")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive REPL mode")
    parser.add_argument("--cwd",        default=".", help="Working directory for agents")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
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
        # Default: planning mode
        run_goal(goal, cwd, claude, codex, plan_only=args.plan_only)


if __name__ == "__main__":
    main()

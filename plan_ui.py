"""
Interactive plan editor: display the generated plan and let the user
review, reassign agents, edit prompts, add/delete tasks, then execute.
"""
from __future__ import annotations

import copy
import sys
import textwrap
from typing import Optional

from model_selector import get_model_emoji, get_model_label, select_model_for_task

# ─── Colors ───────────────────────────────────────────────────────────────────
_USE_COLOR = sys.stdout.isatty()

def _c(text: str, *styles: str) -> str:
    if not _USE_COLOR:
        return text
    codes = {
        "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
        "cyan": "\033[96m",  "green": "\033[92m", "yellow": "\033[93m",
        "red": "\033[91m",   "blue": "\033[94m",  "magenta": "\033[95m",
        "white": "\033[97m",
    }
    return "".join(codes.get(s, "") for s in styles) + text + codes["reset"]


AGENT_COLORS = {"claude": "cyan", "codex": "green"}


def agent_badge(agent: str) -> str:
    color = AGENT_COLORS.get(agent, "white")
    label = f" {agent.upper():6} "
    return _c(label, color, "bold")


# ─── Plan rendering ────────────────────────────────────────────────────────────
def print_plan(plan: dict, verbose: bool = False) -> None:
    tasks = plan["tasks"]
    goal = plan.get("goal", "")
    summary = plan.get("summary", "")

    width = 70
    print()
    print(_c("╔" + "═" * (width - 2) + "╗", "cyan"))
    print(_c("║", "cyan") + _c(f"  PLAN: {goal[:width-10]}", "bold").ljust(width - 2) + _c("║", "cyan"))
    if summary:
        print(_c("║", "cyan") + _c(f"  {summary[:width-4]}", "dim").ljust(width - 2) + _c("║", "cyan"))
    print(_c("╚" + "═" * (width - 2) + "╝", "cyan"))
    print()

    # Header
    print(f"  {'#':>2}  {'Agent':8}  {'Model':10}  {'Title'}")
    print("  " + "─" * (width - 4))

    for t in tasks:
        tid = t["id"]
        agent = t["agent"]
        title = t["title"]
        badge = agent_badge(agent)

        # Show model info for all tasks
        model_str = ""
        if "model" in t:
            model = t["model"]
            emoji = get_model_emoji(model)
            label = get_model_label(model)
            model_str = f"{emoji} {_c(label, 'dim'):8}"
        else:
            model_str = " " * 10

        dep_str = ""
        if t["depends_on"]:
            dep_str = _c(f"  (after {t['depends_on']})", "dim")
        par_str = _c("  ∥parallel", "yellow") if t.get("parallel") else ""
        print(f"  {tid:>2}  {badge}  {model_str}  {title}{dep_str}{par_str}")

        if verbose:
            wrapped = textwrap.fill(t["prompt"], width=width - 8, initial_indent="        ", subsequent_indent="        ")
            print(_c(wrapped, "dim"))
            print()

    print()


def print_help() -> None:
    cmds = [
        ("Enter / go",  "Execute the plan as shown"),
        ("r <n> <agent>","Reassign task n to 'claude' or 'codex'"),
        ("e <n>",        "Edit task n's prompt interactively"),
        ("v <n>",        "View full prompt of task n"),
        ("d <n>",        "Delete task n"),
        ("a",            "Add a new task"),
        ("p <n>",        "Toggle parallel flag for task n"),
        ("dep <n> <ids>","Set dependencies, e.g. 'dep 3 1 2'"),
        ("show",         "Refresh the plan view"),
        ("verbose",      "Toggle verbose (show prompts)"),
        ("q / quit",     "Cancel without executing"),
    ]
    print(_c("\nCommands:", "bold"))
    for cmd, desc in cmds:
        print(f"  {_c(cmd, 'yellow'):30}  {desc}")
    print()


# ─── Plan editing ──────────────────────────────────────────────────────────────
def _find_task(tasks: list, tid: int) -> Optional[dict]:
    for t in tasks:
        if t["id"] == tid:
            return t
    return None


def _next_id(tasks: list) -> int:
    return max((t["id"] for t in tasks), default=0) + 1


def edit_plan(plan: dict) -> Optional[dict]:
    """
    Interactive plan editor.
    Returns the (possibly modified) plan dict, or None if the user cancels.
    """
    plan = copy.deepcopy(plan)
    verbose = False

    print_plan(plan, verbose=verbose)
    print_help()

    while True:
        try:
            raw = input(_c("plan> ", "yellow", "bold")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if not raw:
            return plan  # Enter → execute

        parts = raw.split()
        cmd = parts[0].lower()

        # ── go / execute ──────────────────────────────────────────────
        if cmd in ("go", "run", "exec", "execute"):
            return plan

        # ── quit ─────────────────────────────────────────────────────
        if cmd in ("q", "quit", "cancel", "exit"):
            return None

        # ── show ─────────────────────────────────────────────────────
        if cmd == "show":
            print_plan(plan, verbose=verbose)
            continue

        # ── verbose ──────────────────────────────────────────────────
        if cmd == "verbose":
            verbose = not verbose
            print_plan(plan, verbose=verbose)
            continue

        # ── help ─────────────────────────────────────────────────────
        if cmd in ("h", "help", "?"):
            print_help()
            continue

        # ── reassign: r <n> <agent> ───────────────────────────────────
        if cmd == "r" and len(parts) >= 3:
            try:
                tid = int(parts[1])
                new_agent = parts[2].lower()
            except ValueError:
                print(_c("Usage: r <task_id> <claude|codex>", "red"))
                continue
            if new_agent not in ("claude", "codex"):
                print(_c("Agent must be 'claude' or 'codex'", "red"))
                continue
            t = _find_task(plan["tasks"], tid)
            if not t:
                print(_c(f"Task {tid} not found", "red"))
                continue
            t["agent"] = new_agent
            print(_c(f"✓ Task {tid} → {new_agent.upper()}", "green"))
            print_plan(plan, verbose=verbose)
            continue

        # ── view prompt: v <n> ────────────────────────────────────────
        if cmd == "v" and len(parts) >= 2:
            try:
                tid = int(parts[1])
            except ValueError:
                print(_c("Usage: v <task_id>", "red"))
                continue
            t = _find_task(plan["tasks"], tid)
            if not t:
                print(_c(f"Task {tid} not found", "red"))
                continue
            task_header = f"Task {tid}: {t['title']}"
            print(f"\n{_c(task_header, 'bold')}")
            print(f"Agent: {agent_badge(t['agent'])}")
            print(f"\nPrompt:\n{t['prompt']}\n")
            continue

        # ── edit prompt: e <n> ────────────────────────────────────────
        if cmd == "e" and len(parts) >= 2:
            try:
                tid = int(parts[1])
            except ValueError:
                print(_c("Usage: e <task_id>", "red"))
                continue
            t = _find_task(plan["tasks"], tid)
            if not t:
                print(_c(f"Task {tid} not found", "red"))
                continue
            print(f"\nCurrent prompt for Task {tid}:")
            print(_c(t["prompt"], "dim"))
            print(_c("\nEnter new prompt (empty line to finish, 'cancel' to abort):", "yellow"))
            lines = []
            try:
                while True:
                    line = input("  ").rstrip()
                    if line.lower() == "cancel":
                        lines = None
                        break
                    if line == "" and lines:
                        break
                    if line:
                        lines.append(line)
            except (EOFError, KeyboardInterrupt):
                lines = None
            if lines:
                t["prompt"] = " ".join(lines)
                print(_c("✓ Prompt updated", "green"))
            else:
                print(_c("Edit cancelled", "dim"))
            continue

        # ── delete: d <n> ────────────────────────────────────────────
        if cmd == "d" and len(parts) >= 2:
            try:
                tid = int(parts[1])
            except ValueError:
                print(_c("Usage: d <task_id>", "red"))
                continue
            before = len(plan["tasks"])
            plan["tasks"] = [t for t in plan["tasks"] if t["id"] != tid]
            if len(plan["tasks"]) < before:
                # Remove dead dependencies
                for t in plan["tasks"]:
                    t["depends_on"] = [d for d in t["depends_on"] if d != tid]
                print(_c(f"✓ Task {tid} deleted", "green"))
                print_plan(plan, verbose=verbose)
            else:
                print(_c(f"Task {tid} not found", "red"))
            continue

        # ── add task: a ───────────────────────────────────────────────
        if cmd == "a":
            try:
                print(_c("\nTitle: ", "yellow"), end="")
                title = input().strip()
                print(_c("Agent (claude/codex): ", "yellow"), end="")
                agent = input().strip().lower() or "claude"
                if agent not in ("claude", "codex"):
                    agent = "claude"
                print(_c("Prompt (one line): ", "yellow"), end="")
                prompt = input().strip()
                print(_c("Depends on (space-separated IDs, or Enter for none): ", "yellow"), end="")
                dep_raw = input().strip()
                depends_on = [int(x) for x in dep_raw.split() if x.isdigit()]
            except (EOFError, KeyboardInterrupt):
                print(_c("\nAdd cancelled", "dim"))
                continue
            new_task = {
                "id": _next_id(plan["tasks"]),
                "title": title or "New task",
                "agent": agent,
                "prompt": prompt,
                "depends_on": depends_on,
                "parallel": False,
            }
            # Auto-select model for all tasks
            new_task["model"] = select_model_for_task(new_task)
            plan["tasks"].append(new_task)
            print(_c(f"✓ Task {new_task['id']} added", "green"))
            print_plan(plan, verbose=verbose)
            continue

        # ── parallel toggle: p <n> ────────────────────────────────────
        if cmd == "p" and len(parts) >= 2:
            try:
                tid = int(parts[1])
            except ValueError:
                print(_c("Usage: p <task_id>", "red"))
                continue
            t = _find_task(plan["tasks"], tid)
            if not t:
                print(_c(f"Task {tid} not found", "red"))
                continue
            t["parallel"] = not t.get("parallel", False)
            state = "parallel ∥" if t["parallel"] else "sequential"
            print(_c(f"✓ Task {tid} → {state}", "green"))
            continue

        # ── dependencies: dep <n> <ids...> ────────────────────────────
        if cmd == "dep" and len(parts) >= 2:
            try:
                tid = int(parts[1])
                deps = [int(x) for x in parts[2:]]
            except ValueError:
                print(_c("Usage: dep <task_id> <dep_id1> [dep_id2 ...]", "red"))
                continue
            t = _find_task(plan["tasks"], tid)
            if not t:
                print(_c(f"Task {tid} not found", "red"))
                continue
            t["depends_on"] = deps
            print(_c(f"✓ Task {tid} depends on {deps}", "green"))
            continue

        print(_c(f"Unknown command: '{raw}'. Type 'h' for help.", "dim"))

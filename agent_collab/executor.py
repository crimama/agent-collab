"""
Executor: runs a plan's tasks in dependency order,
passing previous outputs as context to subsequent tasks.
Supports parallel execution of independent tasks.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Dict, List, Optional

from agent_collab.agents import ClaudeAgent, CodexAgent
from agent_collab.agents.base import AgentResult

# ─── Colors ───────────────────────────────────────────────────────────────────
_USE_COLOR = sys.stdout.isatty()

def _c(text: str, *styles: str) -> str:
    if not _USE_COLOR:
        return text
    codes = {
        "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
        "cyan": "\033[96m",  "green": "\033[92m", "yellow": "\033[93m",
        "red": "\033[91m",   "blue": "\033[94m",
    }
    return "".join(codes.get(s, "") for s in styles) + text + codes["reset"]


SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _build_context_prefix(
    completed: Dict[int, AgentResult],
    depends_on: List[int],
    additional_context: str = ""
) -> str:
    """Build a context string from outputs of tasks this task depends on + global context."""
    parts = []

    # Add global additional context if present
    if additional_context and additional_context.strip():
        parts.append(f"=== Global Instructions ===\n{additional_context.strip()}")

    # Add dependency outputs
    for dep_id in depends_on:
        res = completed.get(dep_id)
        if res and res.output.strip():
            out = res.output.strip()
            # Trim very long outputs to avoid bloat
            if len(out) > 2000:
                out = out[:2000] + "\n... [truncated]"
            parts.append(f"=== Output from Task {dep_id} ({res.agent_name.upper()}) ===\n{out}")

    if not parts:
        return ""
    return "\n\n".join(parts) + "\n\n--- Your task ---\n"


# ─── Topological sort ─────────────────────────────────────────────────────────
def _topo_sort(tasks: list) -> List[List[dict]]:
    """
    Returns tasks grouped into waves (each wave can run in parallel).
    Wave i runs after wave i-1 completes.
    """
    id_map = {t["id"]: t for t in tasks}
    in_degree = {t["id"]: len(t.get("depends_on", [])) for t in tasks}
    remaining = set(t["id"] for t in tasks)
    waves = []

    while remaining:
        # Tasks with no unresolved dependencies
        wave_ids = [tid for tid in remaining if in_degree[tid] == 0]
        if not wave_ids:
            # Cycle or error — just dump remaining tasks
            wave_ids = list(remaining)
        waves.append([id_map[tid] for tid in sorted(wave_ids)])
        for tid in wave_ids:
            remaining.remove(tid)
            # Reduce in-degree of dependents
            for t in tasks:
                if tid in t.get("depends_on", []) and t["id"] in remaining:
                    in_degree[t["id"]] -= 1

    return waves


# ─── Single-task runner ────────────────────────────────────────────────────────
def _run_task_with_spinner(
    agent,
    task: dict,
    context_prefix: str,
    cwd: str,
) -> AgentResult:
    full_prompt = context_prefix + task["prompt"]
    done = threading.Event()

    def _spin():
        i = 0
        label = _c(agent.name.upper(), "cyan" if agent.name == "claude" else "green")
        while not done.is_set():
            sys.stderr.write(
                f"\r  {SPINNER[i % len(SPINNER)]}  [{label}] {task['title']} ..."
            )
            sys.stderr.flush()
            time.sleep(0.12)
            i += 1
        sys.stderr.write("\r" + " " * 70 + "\r")
        sys.stderr.flush()

    spin_t = threading.Thread(target=_spin, daemon=True)
    spin_started = sys.stderr.isatty()
    if spin_started:
        spin_t.start()

    result = agent.run(full_prompt, cwd=cwd)
    done.set()
    if spin_started:
        spin_t.join(timeout=0.5)
    return result


def _run_task_async(
    agent,
    task: dict,
    context_prefix: str,
    cwd: str,
    results: dict,
) -> threading.Thread:
    def _worker():
        results[task["id"]] = _run_task_with_spinner(agent, task, context_prefix, cwd)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t


# ─── Main executor ─────────────────────────────────────────────────────────────
def execute_plan(
    plan: dict,
    cwd: str = ".",
    claude: Optional[ClaudeAgent] = None,
    codex: Optional[CodexAgent] = None,
    save_results: bool = True,
    session=None,                        # session_store.Session | None
    skip_task_ids: Optional[List[int]] = None,  # already-done task IDs (resume)
) -> Dict[int, AgentResult]:
    """Execute the plan. Returns a dict of {task_id: AgentResult}."""
    if claude is None:
        claude = ClaudeAgent()
    if codex is None:
        codex = CodexAgent()

    skip_ids = set(skip_task_ids or [])
    agent_map = {"claude": claude, "codex": codex}
    tasks = plan["tasks"]
    waves = _topo_sort(tasks)

    # Pre-populate completed from session outputs (for context injection on resume)
    completed: Dict[int, AgentResult] = {}
    if session and skip_ids:
        for tid in skip_ids:
            cached = session.task_outputs.get(str(tid), "")
            task_obj = next((t for t in tasks if t["id"] == tid), None)
            if task_obj and cached:
                completed[tid] = AgentResult(
                    agent_name=task_obj.get("agent", "claude"),
                    task=task_obj.get("prompt", ""),
                    output=cached, error="", returncode=0, duration_s=0,
                )

    total = len(tasks)
    remaining = total - len(skip_ids)
    done_count = len(skip_ids)

    print()
    if skip_ids:
        print(_c(f"Resuming — skipping {len(skip_ids)} completed task(s), "
                 f"running {remaining} remaining...", "yellow", "bold"))
    else:
        print(_c(f"Executing {total} tasks in {len(waves)} wave(s)...", "bold"))
    print()

    for wave_idx, wave in enumerate(waves):
        # Filter out already-done tasks
        todo_wave = [t for t in wave if t["id"] not in skip_ids]
        if not todo_wave:
            continue

        parallel_tasks = [t for t in todo_wave if t.get("parallel") and len(todo_wave) > 1]
        serial_tasks   = [t for t in todo_wave if not t.get("parallel") or len(todo_wave) == 1]

        # ── Parallel tasks in this wave ────────────────────────────────
        if parallel_tasks:
            print(_c(f"  ∥ Wave {wave_idx+1}: running {len(parallel_tasks)} tasks in parallel", "yellow"))
            async_results: Dict[int, AgentResult] = {}
            threads = []
            for t in parallel_tasks:
                ctx = _build_context_prefix(
                    completed,
                    t.get("depends_on", []),
                    plan.get("additional_context", "")
                )
                agent = agent_map.get(t["agent"], claude)
                threads.append(_run_task_async(agent, t, ctx, cwd, async_results))
            for th in threads:
                th.join()
            for t in parallel_tasks:
                res = async_results.get(t["id"])
                if res:
                    completed[t["id"]] = res
                    done_count += 1
                    _print_result(t, res, done_count, total)
                    if session:
                        session.mark_task_done(t["id"], res.output)

        # ── Serial tasks in this wave ──────────────────────────────────
        for t in serial_tasks:
            ctx = _build_context_prefix(
                completed,
                t.get("depends_on", []),
                plan.get("additional_context", "")
            )
            agent = agent_map.get(t["agent"], claude)
            result = _run_task_with_spinner(agent, t, ctx, cwd)
            completed[t["id"]] = result
            done_count += 1
            _print_result(t, result, done_count, total)
            if session:
                session.mark_task_done(t["id"], result.output)

    print()
    print(_c(f"✓ All {total} tasks complete.", "green", "bold"))
    print()

    if session:
        session.mark_completed()

    if save_results:
        _save_results(plan, completed)

    return completed


_PREVIEW_LINES = 18   # max lines shown inline; rest collapsed


def _print_result(task: dict, result: AgentResult, done: int, total: int) -> None:
    agent  = result.agent_name
    color  = "cyan" if agent == "claude" else "green"
    status = _c("✓", "green") if result.success else _c("✗", "red")

    # Agent-specific styling
    if agent == "claude":
        icon = "🤖"
        border_char = "═"
        side_char = "║"
    else:
        icon = "💻"
        border_char = "─"
        side_char = "│"

    badge  = _c(f"{icon} {agent.upper()}", color, "bold")
    prog   = _c(f"[{done}/{total}]", "dim")
    t_str  = _c(f"{result.duration_s:.1f}s", "dim")
    title  = task["title"]

    # ── Header box with agent-specific styling ──────────────────────────────
    width = 70
    print()
    print(_c(f"  ╔{border_char * width}╗", color))

    # Title line
    title_line = f"  {side_char} {status} {badge}  {title}"
    padding = width - len(f"{status} {icon} {agent.upper()}  {title}") + 8  # +8 for ANSI codes
    print(title_line + " " * max(0, padding) + _c(side_char, color))

    # Metadata line
    meta = f"  {side_char} {t_str}  {prog}"
    meta_padding = width - len(f"{result.duration_s:.1f}s  [{done}/{total}]") + 6
    print(_c(meta, "dim") + " " * max(0, meta_padding) + _c(side_char, color))

    print(_c(f"  ╚{border_char * width}╝", color))

    if not result.success:
        print(_c(f"  ✖ {result.error[:200]}", "red"))
        print()
        return

    out = result.output.strip()
    if not out:
        print()
        return

    lines = out.splitlines()
    preview = lines[:_PREVIEW_LINES]
    hidden  = len(lines) - _PREVIEW_LINES

    # ── Content box with agent color borders ────────────────────────────────
    print(_c(f"  {side_char}", color) + _c("─" * (width - 1), "dim"))
    for line in preview:
        # Trim very long lines
        display = line[:width - 5] + _c(" …", "dim") if len(line) > width - 5 else line
        print(_c(f"  {side_char} ", color) + display)

    if hidden > 0:
        print(_c(f"  {side_char} ", color) + _c(f"╌╌ +{hidden} more lines (saved to results file) ╌╌", "dim"))

    print(_c(f"  {side_char}", color) + _c("─" * (width - 1), "dim"))
    print()


def _save_results(plan: dict, completed: Dict[int, AgentResult]) -> None:
    """Save results to a markdown file."""
    import os
    from datetime import datetime

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"collab_results_{ts}.md"
    goal = plan.get("goal", "unknown")

    lines = [
        f"# agent-collab Results\n",
        f"**Goal:** {goal}\n",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        "",
    ]
    for task in plan["tasks"]:
        tid = task["id"]
        res = completed.get(tid)
        if not res:
            continue
        lines += [
            f"## Task {tid}: {task['title']} [{task['agent'].upper()}]",
            "",
            f"**Prompt:** {task['prompt']}",
            "",
            "**Output:**",
            "```",
            res.output.strip(),
            "```",
            "",
        ]

    with open(fname, "w") as f:
        f.write("\n".join(lines))

    print(_c(f"Results saved → {fname}", "dim"))

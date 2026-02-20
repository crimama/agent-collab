"""Planner: uses Claude to decompose a development goal into subtasks."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile

# ── System prompt: override project CLAUDE.md context ─────────────────────────
_SYSTEM_PROMPT = (
    "You are a JSON-only task planner. "
    "You MUST respond with ONLY a valid JSON object. "
    "Do NOT include any explanation, markdown, code fences, or any text outside the JSON. "
    "Your entire response must be parseable by json.loads()."
)

_PLAN_PROMPT = """\
Break this development goal into 3-8 concrete, actionable subtasks.

CRITICAL: Balance task assignment between both agents based on task type:
- "claude": reasoning, analysis, architecture, code review, refactoring, documentation, debugging complex logic
- "codex":  code generation, boilerplate, tests, API implementations, data processing, quick fixes

Use BOTH agents - assign implementation/coding tasks to "codex", analytical/review tasks to "claude".

Goal: {goal}
Working directory: {cwd}

Example output format (use BOTH agents):
{{"goal":"Build REST API","summary":"Create FastAPI backend","tasks":[{{"id":1,"title":"Design API architecture","prompt":"Design REST API structure and endpoints","agent":"claude","depends_on":[],"parallel":false}},{{"id":2,"title":"Implement CRUD endpoints","prompt":"Generate FastAPI CRUD code","agent":"codex","depends_on":[1],"parallel":false}},{{"id":3,"title":"Write test suite","prompt":"Create pytest tests","agent":"codex","depends_on":[2],"parallel":false}},{{"id":4,"title":"Review and optimize","prompt":"Review code quality and suggest improvements","agent":"claude","depends_on":[3],"parallel":false}}]}}

Output ONLY valid JSON (no fences, no text before or after):"""


def _extract_json(text: str) -> str:
    """Extract JSON object from text, handling markdown fences and surrounding prose."""
    # 1. Try fenced code block first: ```json ... ``` or ``` ... ```
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if fenced:
        return fenced.group(1)
    # 2. Find outermost { ... } spanning the whole response
    start = text.find("{")
    if start == -1:
        return ""
    depth, end = 0, -1
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    return text[start : end + 1] if end != -1 else ""


def _run_planner(goal: str, cwd: str) -> str:
    """Call `claude --print` with a neutral (temp) working dir to avoid project context."""
    import signal

    prompt = _PLAN_PROMPT.format(
        goal=goal,
        cwd=cwd,
        goal_escaped=goal.replace('"', '\\"').replace("\n", " "),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            proc = subprocess.run(
                [
                    "claude", "--print",
                    "--system-prompt", _SYSTEM_PROMPT,
                    "--output-format", "text",
                    "--permission-mode", "bypassPermissions",
                    "--no-session-persistence",
                    prompt,
                ],
                capture_output=True,
                text=True,
                cwd=tmpdir,   # neutral dir — no CLAUDE.md, no project context
                timeout=120,  # 2 minute timeout
            )
            return proc.stdout.strip()
        except KeyboardInterrupt:
            import sys
            print("\n\n" + "\033[91m" + "✖ Planning cancelled by user (Ctrl+C)" + "\033[0m", file=sys.stderr)
            raise
        except subprocess.TimeoutExpired:
            import sys
            print("\n\n" + "\033[91m" + "✖ Planning timed out (>2 minutes)" + "\033[0m", file=sys.stderr)
            raise KeyboardInterrupt("Planning timeout")


def _auto_detect_parallel_tasks(tasks: list) -> None:
    """
    Automatically mark tasks as parallel if they can run concurrently.
    Tasks are parallelizable if they:
    1. Have no dependencies on each other
    2. Only depend on already-completed tasks (earlier IDs)
    """
    # Build dependency map
    task_ids = [t["id"] for t in tasks]

    # Group tasks by their maximum dependency ID
    # Tasks with the same max_dep can potentially run in parallel
    groups: dict[int, list] = {}
    for t in tasks:
        deps = t.get("depends_on", [])
        max_dep = max(deps) if deps else 0
        if max_dep not in groups:
            groups[max_dep] = []
        groups[max_dep].append(t)

    # Mark tasks as parallel if there are multiple tasks in the same group
    for max_dep, group_tasks in groups.items():
        if len(group_tasks) >= 2:
            # Multiple tasks with same dependencies can run in parallel
            for t in group_tasks:
                t["parallel"] = True


def generate_plan(goal: str, cwd: str = ".", max_retries: int = 2, auto_parallel: bool = True) -> dict:
    """Call Claude to decompose `goal` into a structured plan. Retries on parse failure."""
    last_error = None

    for attempt in range(1, max_retries + 2):  # attempts = max_retries + 1
        try:
            raw = _run_planner(goal, cwd)
        except KeyboardInterrupt:
            # User cancelled - exit cleanly
            import sys
            print("\n  \033[93mPlanning cancelled. Returning to prompt.\033[0m\n", file=sys.stderr)
            raise
        json_str = _extract_json(raw)

        if not json_str:
            last_error = ValueError(
                f"No JSON found in Claude output (attempt {attempt}):\n{raw[:400]}"
            )
            continue

        try:
            plan = json.loads(json_str)
        except json.JSONDecodeError as e:
            last_error = ValueError(
                f"Invalid JSON from planner (attempt {attempt}):\n{e}\n\n{json_str[:400]}"
            )
            continue

        if "tasks" not in plan or not isinstance(plan["tasks"], list):
            last_error = ValueError(f"Plan missing 'tasks' list (attempt {attempt}):\n{plan}")
            continue

        # Success — normalise fields
        for i, t in enumerate(plan["tasks"]):
            t.setdefault("id", i + 1)
            t.setdefault("title", f"Task {i + 1}")
            t.setdefault("agent", "claude")
            t.setdefault("depends_on", [])
            t.setdefault("parallel", False)
            t.setdefault("prompt", "")

        # Auto-detect parallel tasks if enabled
        if auto_parallel:
            _auto_detect_parallel_tasks(plan["tasks"])
            parallel_count = sum(1 for t in plan["tasks"] if t.get("parallel"))
            if parallel_count > 0:
                import sys
                print(f"  ⚡ {parallel_count} task(s) will run in parallel for faster execution", file=sys.stderr)

        # Warn if all tasks assigned to same agent
        agents = [t["agent"] for t in plan["tasks"]]
        if len(set(agents)) == 1 and len(agents) > 1:
            import sys
            dominant = agents[0]
            print(f"\n⚠️  Warning: All {len(agents)} tasks assigned to {dominant.upper()}.", file=sys.stderr)
            print(f"   Consider reassigning some tasks in the plan editor.", file=sys.stderr)
            print(f"   Use 'r <task_id> codex' or 'r <task_id> claude'\n", file=sys.stderr)

        return plan

    raise last_error  # all attempts failed

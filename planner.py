"""Planner: uses Claude to decompose a development goal into subtasks."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile

from model_selector import select_model_for_task

# ── System prompt: override project CLAUDE.md context ─────────────────────────
_SYSTEM_PROMPT = (
    "You are a JSON-only task planner. "
    "You MUST respond with ONLY a valid JSON object. "
    "Do NOT include any explanation, markdown, code fences, or any text outside the JSON. "
    "Your entire response must be parseable by json.loads()."
)

_PLAN_PROMPT = """\
Break this development goal into 3-8 concrete, actionable subtasks.

Assign each task to:
- "claude": reasoning, analysis, architecture, code review, documentation
- "codex":  code generation, tests, implementation, boilerplate

Goal: {goal}
Working directory: {cwd}

Output ONLY this JSON (no fences, no text before or after):
{{"goal":"{goal_escaped}","summary":"one sentence","tasks":[{{"id":1,"title":"max 8 words","prompt":"detailed self-contained prompt","agent":"claude","depends_on":[],"parallel":false}}]}}"""


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
    prompt = _PLAN_PROMPT.format(
        goal=goal,
        cwd=cwd,
        goal_escaped=goal.replace('"', '\\"').replace("\n", " "),
    )
    with tempfile.TemporaryDirectory() as tmpdir:
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
        )
    return proc.stdout.strip()


def generate_plan(goal: str, cwd: str = ".", max_retries: int = 2) -> dict:
    """Call Claude to decompose `goal` into a structured plan. Retries on parse failure."""
    last_error = None

    for attempt in range(1, max_retries + 2):  # attempts = max_retries + 1
        raw = _run_planner(goal, cwd)
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
            # Auto-select appropriate model based on task complexity
            t["model"] = select_model_for_task(t)
        return plan

    raise last_error  # all attempts failed

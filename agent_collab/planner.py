"""Planner: uses Claude to decompose a development goal into subtasks."""
from __future__ import annotations

import json
import re
import subprocess

PLAN_PROMPT = """\
You are a software development task planner.

Break the following goal into 3-8 concrete, actionable subtasks.
Assign each task to the most appropriate agent:

- "claude": architecture design, complex reasoning, analysis, debugging,
            code review, documentation, strategy, understanding codebase
- "codex":  code generation, writing tests, implementing functions,
            creating files, boilerplate, refactoring specific code

Rules:
1. Each task prompt must be self-contained and specific enough for the agent to act on alone.
2. Respect natural dependencies (depends_on: list of task IDs that must finish first).
3. Tasks with no dependencies and no conflicts can run in parallel (parallel: true).
4. Keep titles ≤ 8 words.

Goal: {goal}
Working directory: {cwd}

Respond with ONLY valid JSON — no markdown fences, no explanation:
{{
  "goal": "{goal_escaped}",
  "summary": "One sentence: what will be built/achieved",
  "tasks": [
    {{
      "id": 1,
      "title": "Short action title",
      "prompt": "Detailed, self-contained prompt for the agent.",
      "agent": "claude",
      "depends_on": [],
      "parallel": false
    }}
  ]
}}"""


def generate_plan(goal: str, cwd: str = ".") -> dict:
    prompt = PLAN_PROMPT.format(
        goal=goal,
        cwd=cwd,
        goal_escaped=goal.replace('"', '\\"'),
    )
    proc = subprocess.run(
        ["claude", "--print", "--output-format", "text",
         "--permission-mode", "bypassPermissions", prompt],
        capture_output=True, text=True,
    )
    raw = proc.stdout.strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError(f"Planner could not parse JSON from Claude output.\n\n{raw[:500]}")
    try:
        plan = json.loads(match.group())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from planner:\n{e}\n\n{match.group()[:500]}")
    if "tasks" not in plan or not isinstance(plan["tasks"], list):
        raise ValueError(f"Plan missing 'tasks' list:\n{plan}")
    for i, t in enumerate(plan["tasks"]):
        t.setdefault("id", i + 1)
        t.setdefault("title", f"Task {i + 1}")
        t.setdefault("agent", "claude")
        t.setdefault("depends_on", [])
        t.setdefault("parallel", False)
        t.setdefault("prompt", "")
    return plan

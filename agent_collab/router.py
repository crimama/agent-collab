"""Task routing logic: decides whether Claude Code or Codex CLI should handle a task."""
from __future__ import annotations

import re
from typing import Literal

AgentChoice = Literal["claude", "codex"]


def classify_task(task: str, config: dict) -> AgentChoice:
    task_lower = task.lower()
    claude_score = sum(1 for kw in config["routing"]["claude_keywords"] if _word_in_text(kw, task_lower))
    codex_score  = sum(1 for kw in config["routing"]["codex_keywords"]  if _word_in_text(kw, task_lower))
    if claude_score == codex_score:
        return config.get("default_agent", "claude")
    return "claude" if claude_score > codex_score else "codex"


def _word_in_text(keyword: str, text: str) -> bool:
    if " " in keyword:
        return keyword in text
    pattern = rf"(^|[\s.,;:!?\-]){re.escape(keyword)}($|[\s.,;:!?\-])"
    return bool(re.search(pattern, text)) or keyword in text


def explain_routing(task: str, config: dict) -> str:
    task_lower = task.lower()
    matched_claude = [kw for kw in config["routing"]["claude_keywords"] if _word_in_text(kw, task_lower)]
    matched_codex  = [kw for kw in config["routing"]["codex_keywords"]  if _word_in_text(kw, task_lower)]
    chosen = classify_task(task, config)
    lines = [f"Routing decision: → {chosen.upper()}"]
    if matched_claude:
        lines.append(f"  Claude signals ({len(matched_claude)}): {', '.join(matched_claude[:5])}")
    if matched_codex:
        lines.append(f"  Codex signals  ({len(matched_codex)}): {', '.join(matched_codex[:5])}")
    if not matched_claude and not matched_codex:
        lines.append(f"  No keywords matched → default: {config.get('default_agent', 'claude')}")
    return "\n".join(lines)

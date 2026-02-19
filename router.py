"""Task routing logic: decides whether Claude Code or Codex CLI should handle a task."""
from __future__ import annotations

import re
from typing import Literal

AgentChoice = Literal["claude", "codex"]


def classify_task(task: str, config: dict) -> AgentChoice:
    """Route a task to the most appropriate agent based on keyword matching.

    Returns 'claude' or 'codex'.
    """
    task_lower = task.lower()

    claude_score = 0
    codex_score = 0

    for kw in config["routing"]["claude_keywords"]:
        if _word_in_text(kw, task_lower):
            claude_score += 1

    for kw in config["routing"]["codex_keywords"]:
        if _word_in_text(kw, task_lower):
            codex_score += 1

    if claude_score == codex_score:
        return config.get("default_agent", "claude")

    return "claude" if claude_score > codex_score else "codex"


def _word_in_text(keyword: str, text: str) -> bool:
    """Check if a keyword (phrase) appears in text."""
    # Multi-word phrases: simple substring match
    if " " in keyword:
        return keyword in text
    # Single word: word-boundary match (handles English), also plain substring for Korean
    pattern = rf"(^|[\s.,;:!?\-]){re.escape(keyword)}($|[\s.,;:!?\-])"
    return bool(re.search(pattern, text)) or keyword in text


def explain_routing(task: str, config: dict) -> str:
    """Return a human-readable explanation of the routing decision."""
    task_lower = task.lower()

    matched_claude = [kw for kw in config["routing"]["claude_keywords"] if _word_in_text(kw, task_lower)]
    matched_codex = [kw for kw in config["routing"]["codex_keywords"] if _word_in_text(kw, task_lower)]

    chosen = classify_task(task, config)

    lines = [f"Routing decision: → {chosen.upper()}"]
    if matched_claude:
        lines.append(f"  Claude signals ({len(matched_claude)}): {', '.join(matched_claude[:5])}")
    if matched_codex:
        lines.append(f"  Codex signals  ({len(matched_codex)}): {', '.join(matched_codex[:5])}")
    if not matched_claude and not matched_codex:
        lines.append(f"  No keywords matched → default: {config.get('default_agent', 'claude')}")

    return "\n".join(lines)

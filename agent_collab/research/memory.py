"""Research Memory — tracks mistakes, insights, and learnings across rounds."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Optional


@dataclass
class MemoryEntry:
    """Single learning entry (mistake, insight, or pattern)."""
    type: str  # "mistake", "insight", "success", "failure"
    round_num: int
    step_name: str
    content: str
    timestamp: str
    context: str = ""  # Additional context

    def to_markdown(self) -> str:
        """Format entry as markdown."""
        emoji = {
            "mistake": "❌",
            "failure": "⚠️",
            "insight": "💡",
            "success": "✅",
            "pattern": "🔍"
        }.get(self.type, "📝")

        lines = [f"### {emoji} {self.type.title()}: Round {self.round_num} - {self.step_name}"]
        lines.append(f"*{self.timestamp}*\n")
        lines.append(self.content)
        if self.context:
            lines.append(f"\n**Context:** {self.context}")
        return "\n".join(lines)


@dataclass
class ResearchMemory:
    """Accumulates learnings across research rounds."""
    goal: str
    entries: List[MemoryEntry] = field(default_factory=list)
    patterns: Dict[str, List[str]] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def add_mistake(self, round_num: int, step_name: str, content: str, context: str = ""):
        """Record a mistake or failed approach."""
        entry = MemoryEntry(
            type="mistake",
            round_num=round_num,
            step_name=step_name,
            content=content,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            context=context
        )
        self.entries.append(entry)

    def add_insight(self, round_num: int, step_name: str, content: str, context: str = ""):
        """Record a valuable insight or discovery."""
        entry = MemoryEntry(
            type="insight",
            round_num=round_num,
            step_name=step_name,
            content=content,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            context=context
        )
        self.entries.append(entry)

    def add_success(self, round_num: int, step_name: str, content: str, context: str = ""):
        """Record a successful approach or technique."""
        entry = MemoryEntry(
            type="success",
            round_num=round_num,
            step_name=step_name,
            content=content,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            context=context
        )
        self.entries.append(entry)

    def add_failure(self, round_num: int, step_name: str, content: str, context: str = ""):
        """Record a failed experiment or approach."""
        entry = MemoryEntry(
            type="failure",
            round_num=round_num,
            step_name=step_name,
            content=content,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            context=context
        )
        self.entries.append(entry)

    def add_pattern(self, pattern_name: str, observation: str):
        """Record an emerging pattern across rounds."""
        if pattern_name not in self.patterns:
            self.patterns[pattern_name] = []
        self.patterns[pattern_name].append(observation)

    def get_mistakes_context(self, max_recent: int = 10) -> str:
        """Get recent mistakes to avoid repeating them."""
        mistakes = [e for e in self.entries if e.type in ("mistake", "failure")]
        if not mistakes:
            return "No previous mistakes recorded."

        recent = mistakes[-max_recent:]
        lines = ["=== MISTAKES TO AVOID ==="]
        for m in recent:
            lines.append(f"- [R{m.round_num}/{m.step_name}] {m.content}")
        return "\n".join(lines)

    def get_insights_context(self, max_recent: int = 10) -> str:
        """Get recent insights to build upon."""
        insights = [e for e in self.entries if e.type in ("insight", "success")]
        if not insights:
            return "No insights recorded yet."

        recent = insights[-max_recent:]
        lines = ["=== KEY INSIGHTS ==="]
        for i in recent:
            lines.append(f"- [R{i.round_num}/{i.step_name}] {i.content}")
        return "\n".join(lines)

    def get_full_context(self, max_per_type: int = 5) -> str:
        """Get comprehensive memory context for prompts."""
        parts = []

        # Recent mistakes/failures
        mistakes = [e for e in self.entries if e.type in ("mistake", "failure")]
        if mistakes:
            parts.append("🚫 AVOID THESE (Recent Mistakes/Failures):")
            for m in mistakes[-max_per_type:]:
                parts.append(f"  • [R{m.round_num}] {m.content[:200]}")
            parts.append("")

        # Recent insights/successes
        insights = [e for e in self.entries if e.type in ("insight", "success")]
        if insights:
            parts.append("💡 BUILD ON THESE (Key Insights/Successes):")
            for i in insights[-max_per_type:]:
                parts.append(f"  • [R{i.round_num}] {i.content[:200]}")
            parts.append("")

        # Patterns
        if self.patterns:
            parts.append("🔍 EMERGING PATTERNS:")
            for pattern_name, observations in list(self.patterns.items())[-3:]:
                parts.append(f"  • {pattern_name}: {len(observations)} observations")
                if observations:
                    parts.append(f"    Latest: {observations[-1][:150]}")
            parts.append("")

        if not parts:
            return "No learnings recorded yet. This is the first round."

        return "\n".join(parts)

    def extract_learnings_from_output(self, output: str, round_num: int, step_name: str):
        """Automatically extract learnings from agent output using keyword detection."""
        output_lower = output.lower()

        # Detect mistakes/failures
        mistake_keywords = ["mistake", "error", "failed", "didn't work", "wrong approach",
                           "incorrect", "bug", "issue", "problem"]
        for keyword in mistake_keywords:
            if keyword in output_lower:
                # Try to extract context around the keyword
                idx = output_lower.find(keyword)
                context_start = max(0, idx - 50)
                context_end = min(len(output), idx + 150)
                snippet = output[context_start:context_end].strip()
                if len(snippet) > 20:  # Meaningful content
                    self.add_mistake(round_num, step_name, snippet)
                    break

        # Detect insights
        insight_keywords = ["insight:", "discovered", "found that", "key finding",
                          "important:", "learned", "realized"]
        for keyword in insight_keywords:
            if keyword in output_lower:
                idx = output_lower.find(keyword)
                context_start = max(0, idx - 20)
                context_end = min(len(output), idx + 200)
                snippet = output[context_start:context_end].strip()
                if len(snippet) > 20:
                    self.add_insight(round_num, step_name, snippet)
                    break

        # Detect successes
        success_keywords = ["success", "worked well", "improvement", "better than",
                          "achieved", "solved", "optimal"]
        for keyword in success_keywords:
            if keyword in output_lower:
                idx = output_lower.find(keyword)
                context_start = max(0, idx - 50)
                context_end = min(len(output), idx + 150)
                snippet = output[context_start:context_end].strip()
                if len(snippet) > 20:
                    self.add_success(round_num, step_name, snippet)
                    break

    def to_markdown(self) -> str:
        """Generate full markdown report."""
        lines = [
            f"# Research Learning Log",
            f"",
            f"**Research Goal:** {self.goal}",
            f"**Created:** {self.created_at}",
            f"**Total Entries:** {len(self.entries)}",
            f"",
            f"---",
            f""
        ]

        # Summary by type
        by_type = {}
        for entry in self.entries:
            if entry.type not in by_type:
                by_type[entry.type] = []
            by_type[entry.type].append(entry)

        lines.append("## 📊 Summary")
        for entry_type, entries in by_type.items():
            emoji = {"mistake": "❌", "failure": "⚠️", "insight": "💡",
                    "success": "✅", "pattern": "🔍"}.get(entry_type, "📝")
            lines.append(f"- {emoji} {entry_type.title()}: {len(entries)}")
        lines.append("")

        # Patterns
        if self.patterns:
            lines.append("## 🔍 Emerging Patterns")
            for pattern_name, observations in self.patterns.items():
                lines.append(f"\n### {pattern_name}")
                lines.append(f"*{len(observations)} observation(s)*\n")
                for i, obs in enumerate(observations, 1):
                    lines.append(f"{i}. {obs}")
            lines.append("\n---\n")

        # All entries chronologically
        lines.append("## 📝 Chronological Log")
        for entry in self.entries:
            lines.append("")
            lines.append(entry.to_markdown())
            lines.append("")

        return "\n".join(lines)

    def save(self, session_dir: Path) -> Path:
        """Save memory to both JSON and Markdown."""
        # Save JSON for programmatic access
        json_path = session_dir / "research_memory.json"
        data = {
            "goal": self.goal,
            "created_at": self.created_at,
            "entries": [asdict(e) for e in self.entries],
            "patterns": self.patterns
        }
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)

        # Save Markdown for human reading
        md_path = session_dir / "research_learnings.md"
        md_path.write_text(self.to_markdown())

        return md_path

    @classmethod
    def load(cls, session_dir: Path, goal: str = "") -> "ResearchMemory":
        """Load memory from JSON file."""
        json_path = session_dir / "research_memory.json"

        if not json_path.exists():
            return cls(goal=goal)

        with open(json_path) as f:
            data = json.load(f)

        memory = cls(
            goal=data.get("goal", goal),
            created_at=data.get("created_at", ""),
            patterns=data.get("patterns", {})
        )

        for e_data in data.get("entries", []):
            entry = MemoryEntry(**e_data)
            memory.entries.append(entry)

        return memory

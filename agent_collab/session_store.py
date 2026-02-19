"""Session persistence for planning and research modes.

Sessions are stored in ~/.collab/sessions/{session_id}/session.json
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

SESSION_ROOT = Path.home() / ".collab" / "sessions"


def _slug(text: str, max_len: int = 40) -> str:
    """Convert text to a filesystem-safe slug."""
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_-]+", "_", s).strip("_")
    return s[:max_len]


@dataclass
class Session:
    id: str
    type: str           # "planning" | "research"
    goal: str
    cwd: str
    created_at: str
    updated_at: str
    status: str         # "in_progress" | "completed" | "cancelled"

    # planning-specific
    plan: Optional[dict] = None
    completed_task_ids: list = field(default_factory=list)
    task_outputs: dict = field(default_factory=dict)   # task_id(str) → output text

    # research-specific
    research_state_path: Optional[str] = None
    current_round: int = 0
    total_rounds: int = 0

    @property
    def dir(self) -> Path:
        return SESSION_ROOT / self.id

    @property
    def path(self) -> Path:
        return self.dir / "session.json"

    def save(self) -> None:
        self.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    def mark_task_done(self, task_id: int, output: str) -> None:
        if task_id not in self.completed_task_ids:
            self.completed_task_ids.append(task_id)
        self.task_outputs[str(task_id)] = output
        self.save()

    def mark_completed(self) -> None:
        self.status = "completed"
        self.save()

    def mark_cancelled(self) -> None:
        self.status = "cancelled"
        self.save()

    def progress_label(self) -> str:
        if self.type == "planning" and self.plan:
            total = len(self.plan.get("tasks", []))
            done = len(self.completed_task_ids)
            return f"{done}/{total} tasks"
        if self.type == "research":
            return f"Round {self.current_round}/{self.total_rounds}"
        return self.status

    @classmethod
    def load(cls, path: str | Path) -> "Session":
        with open(path) as f:
            data = json.load(f)
        return cls(**data)


# ── Store operations ──────────────────────────────────────────────────────────

def new_planning_session(goal: str, cwd: str, plan: dict) -> Session:
    ts = time.strftime("%Y%m%d_%H%M%S")
    sid = f"{ts}_{_slug(goal)}"
    s = Session(
        id=sid, type="planning", goal=goal, cwd=cwd,
        created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        status="in_progress", plan=plan,
    )
    s.save()
    return s


def new_research_session(goal: str, cwd: str, total_rounds: int,
                          research_state_path: str) -> Session:
    ts = time.strftime("%Y%m%d_%H%M%S")
    sid = f"{ts}_{_slug(goal)}"
    s = Session(
        id=sid, type="research", goal=goal, cwd=cwd,
        created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        status="in_progress",
        research_state_path=research_state_path,
        total_rounds=total_rounds, current_round=0,
    )
    s.save()
    return s


def list_sessions(limit: int = 20) -> list[Session]:
    """Return recent sessions sorted by updated_at descending."""
    if not SESSION_ROOT.exists():
        return []
    sessions = []
    for p in SESSION_ROOT.glob("*/session.json"):
        try:
            sessions.append(Session.load(p))
        except Exception:
            pass
    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return sessions[:limit]


def load_session(session_id: str) -> Optional[Session]:
    p = SESSION_ROOT / session_id / "session.json"
    if not p.exists():
        return None
    return Session.load(p)

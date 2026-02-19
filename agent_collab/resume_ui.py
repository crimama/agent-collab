"""Interactive session picker for `collab resume`."""
from __future__ import annotations

import sys
from typing import Optional

from agent_collab.session_store import Session, list_sessions, load_session

_USE_COLOR = sys.stdout.isatty()


def _c(text: str, *styles: str) -> str:
    if not _USE_COLOR:
        return text
    codes = {
        "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
        "cyan": "\033[96m", "green": "\033[92m", "yellow": "\033[93m",
        "red": "\033[91m",  "magenta": "\033[95m", "white": "\033[97m",
    }
    return "".join(codes.get(s, "") for s in styles) + text + codes["reset"]


_TYPE_COLOR = {"planning": "cyan", "research": "magenta"}
_STATUS_COLOR = {"in_progress": "yellow", "completed": "green", "cancelled": "dim"}


def _fmt_session(idx: int, s: Session) -> str:
    type_badge = _c(f" {s.type.upper():8} ", _TYPE_COLOR.get(s.type, "white"), "bold")
    status     = _c(s.status.replace("_", " "), _STATUS_COLOR.get(s.status, "white"))
    progress   = _c(f"({s.progress_label()})", "dim")
    goal       = s.goal[:55] + ("…" if len(s.goal) > 55 else "")
    date       = _c(s.updated_at[:16], "dim")
    return f"  {_c(str(idx), 'bold'):>4}  {type_badge}  {date}  {goal}  {progress}  [{status}]"


def pick_session(session_id: Optional[str] = None) -> Optional[Session]:
    """
    If session_id is given, load and return that session directly.
    Otherwise show an interactive list and let the user pick.
    Returns None if cancelled.
    """
    if session_id:
        s = load_session(session_id)
        if s is None:
            print(_c(f"Session '{session_id}' not found.", "red"))
            return None
        return s

    sessions = list_sessions()
    if not sessions:
        print(_c("No saved sessions found.", "dim"))
        print(_c("Sessions are created automatically when you run `collab`.", "dim"))
        return None

    print()
    print(_c("Recent sessions:", "bold"))
    print()
    for i, s in enumerate(sessions, 1):
        print(_fmt_session(i, s))
    print()
    print(_c("  Commands: <number> to resume  |  d <number> to delete  |  q to cancel", "dim"))
    print()

    while True:
        try:
            raw = input(_c("resume> ", "yellow", "bold")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if raw in ("q", "quit", "cancel", ""):
            return None

        # Delete a session
        if raw.startswith("d "):
            try:
                idx = int(raw[2:].strip()) - 1
                s = sessions[idx]
            except (ValueError, IndexError):
                print(_c("Invalid index.", "red"))
                continue
            confirm = input(_c(f"Delete '{s.goal[:40]}'? (y/N) ", "red")).strip().lower()
            if confirm == "y":
                import shutil
                shutil.rmtree(s.dir, ignore_errors=True)
                sessions.pop(idx)
                print(_c("Deleted.", "dim"))
                if not sessions:
                    print(_c("No sessions left.", "dim"))
                    return None
                for i, ss in enumerate(sessions, 1):
                    print(_fmt_session(i, ss))
            continue

        try:
            idx = int(raw) - 1
            if not (0 <= idx < len(sessions)):
                raise ValueError
            return sessions[idx]
        except ValueError:
            print(_c(f"Enter a number between 1 and {len(sessions)}, or 'q'.", "dim"))

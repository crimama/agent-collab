"""File reference expansion for agent prompts.

Supported syntaxes:
  /abs/path/to/file.py        — absolute path
  /rel/path/file.py           — path relative to cwd
  @filename.py                — fuzzy search in cwd (recursive)
  @subdir/file.py             — relative path searched from cwd
"""
from __future__ import annotations

import glob
import os
import re
from typing import Optional

# /path/to/file.ext — negative lookbehind skips http://, "strings", etc.
_ABS_REF_RE = re.compile(r'(?<!["\':])(/[\w./_\-]+\.[a-zA-Z0-9]+)')

# @filename.ext or @subdir/file.ext
_AT_REF_RE = re.compile(r'(?<!["\'\w])@([\w./\-_]+\.[a-zA-Z0-9]+)')

_EXT_LANG: dict[str, str] = {
    ".py":   "python",      ".js":   "javascript", ".ts":  "typescript",
    ".sh":   "bash",        ".md":   "markdown",   ".yaml": "yaml",
    ".yml":  "yaml",        ".json": "json",        ".toml": "toml",
    ".txt":  "",            ".csv":  "",            ".cpp":  "cpp",
    ".c":    "c",           ".h":    "c",           ".java": "java",
    ".rs":   "rust",        ".go":   "go",          ".sql":  "sql",
    ".html": "html",        ".css":  "css",         ".ini":  "ini",
    ".cfg":  "ini",         ".log":  "",            ".xml":  "xml",
}

MAX_FILE_BYTES = 32_000   # ~8k tokens per file
MAX_CANDIDATES = 20       # max file candidates to show


def list_file_candidates(pattern: str, cwd: str = ".") -> list[str]:
    """
    List file candidates matching a pattern.

    Args:
        pattern: Search pattern (e.g., "auth", "*.py", "src/")
        cwd: Working directory to search from

    Returns:
        List of matching file paths (relative to cwd)
    """
    import os
    matches = []

    # If pattern is empty or just "*", show common code files
    if not pattern or pattern == "*":
        pattern = "*"
        exts = [".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".cpp", ".c", ".h"]
    else:
        exts = None

    # Search recursively
    for root, dirs, files in os.walk(cwd):
        # Skip hidden directories and common ignore paths
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv", "env", ".git")]

        for filename in files:
            # Skip hidden files
            if filename.startswith("."):
                continue

            # Check extension filter
            if exts and not any(filename.endswith(ext) for ext in exts):
                continue

            # Check pattern match (case-insensitive substring)
            if pattern != "*" and pattern.lower() not in filename.lower():
                # Also check if pattern matches path
                rel_path = os.path.relpath(os.path.join(root, filename), cwd)
                if pattern.lower() not in rel_path.lower():
                    continue

            rel_path = os.path.relpath(os.path.join(root, filename), cwd)
            matches.append(rel_path)

            if len(matches) >= MAX_CANDIDATES * 2:  # Early exit if too many
                break

        if len(matches) >= MAX_CANDIDATES * 2:
            break

    # Sort by: 1) exact filename match, 2) starts with pattern, 3) alphabetical
    def sort_key(path):
        filename = os.path.basename(path)
        lower_name = filename.lower()
        lower_pattern = pattern.lower()

        if lower_name == lower_pattern:
            return (0, path)
        elif lower_name.startswith(lower_pattern):
            return (1, path)
        elif lower_pattern in lower_name:
            return (2, path)
        else:
            return (3, path)

    matches.sort(key=sort_key)
    return matches[:MAX_CANDIDATES]


def _find_by_name(name: str, cwd: str) -> Optional[str]:
    """Search cwd (recursively) for a file whose name or relative path matches."""
    # 1. Exact relative path from cwd
    full = os.path.normpath(os.path.join(cwd, name))
    if os.path.isfile(full):
        return full
    # 2. Recursive glob — find first match anywhere under cwd
    basename = os.path.basename(name)
    matches = glob.glob(os.path.join(cwd, "**", basename), recursive=True)
    # Prefer matches that also match any subdirectory portion
    if len(matches) > 1 and os.sep in name:
        suffix = name.replace("/", os.sep)
        matches = [m for m in matches if m.endswith(suffix)] or matches
    return matches[0] if matches else None


def _read_file(abs_path: str) -> Optional[str]:
    try:
        with open(abs_path, errors="replace") as f:
            content = f.read(MAX_FILE_BYTES)
        if len(content) >= MAX_FILE_BYTES:
            content += "\n... [file truncated]"
        return content
    except OSError:
        return None


def expand_file_refs(text: str, cwd: str = ".") -> tuple[str, list[str]]:
    """
    Scan *text* for /path/file.ext and @filename.ext references.
    For each path that resolves to an existing file, append its content.

    Returns:
        (expanded_text, list_of_absolute_paths_that_were_attached)
    """
    resolved: list[tuple[str, str, str]] = []   # (display, abs_path, content)
    seen: set[str] = set()

    def _try_add(display: str, abs_path: str) -> None:
        abs_path = os.path.normpath(abs_path)
        if abs_path in seen or not os.path.isfile(abs_path):
            return
        content = _read_file(abs_path)
        if content is not None:
            seen.add(abs_path)
            resolved.append((display, abs_path, content))

    # /path refs
    for raw in _ABS_REF_RE.findall(text):
        abs_p = raw if os.path.isabs(raw) else os.path.join(cwd, raw)
        _try_add(raw, abs_p)

    # @name refs
    for raw in _AT_REF_RE.findall(text):
        found = _find_by_name(raw, cwd)
        if found:
            _try_add(f"@{raw}", found)

    if not resolved:
        return text, []

    sections = [text, "\n\n---\n**Attached files:**"]
    for display, abs_path, content in resolved:
        ext   = os.path.splitext(abs_path)[1].lower()
        lang  = _EXT_LANG.get(ext, "")
        lines = content.count("\n") + 1
        sections.append(f"\n### {display}  ({lines} lines)\n```{lang}\n{content}\n```")

    return "\n".join(sections), [r[1] for r in resolved]

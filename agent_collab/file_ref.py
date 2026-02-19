"""File reference expansion: /path/to/file.ext → inline content in prompts."""
from __future__ import annotations

import os
import re

# Matches /path/to/file.ext — requires a file extension to avoid matching bare dirs
# Negative lookbehind: skip if preceded by a quote or word char (e.g. "http://...")
_FILE_REF_RE = re.compile(r'(?<!["\':])(/[\w./_\-]+\.[a-zA-Z0-9]+)')

_EXT_LANG: dict[str, str] = {
    ".py":   "python",      ".js":   "javascript", ".ts":  "typescript",
    ".sh":   "bash",        ".md":   "markdown",   ".yaml":"yaml",
    ".yml":  "yaml",        ".json": "json",        ".toml":"toml",
    ".txt":  "",            ".csv":  "",            ".cpp": "cpp",
    ".c":    "c",           ".h":    "c",           ".java":"java",
    ".rs":   "rust",        ".go":   "go",          ".sql": "sql",
    ".html": "html",        ".css":  "css",         ".ini": "ini",
    ".cfg":  "ini",         ".log":  "",
}

MAX_FILE_BYTES = 32_000   # ~8k tokens per file


def expand_file_refs(text: str, cwd: str = ".") -> tuple[str, list[str]]:
    """
    Scan *text* for /path/to/file.ext references.
    For each path that resolves to an existing file, append its content.

    Returns:
        (expanded_text, list_of_absolute_paths_that_were_attached)
    """
    candidates = _FILE_REF_RE.findall(text)
    if not candidates:
        return text, []

    resolved: list[tuple[str, str, str]] = []   # (display_path, abs_path, content)
    seen: set[str] = set()

    for raw in candidates:
        if raw in seen:
            continue
        seen.add(raw)

        abs_path = os.path.normpath(
            raw if os.path.isabs(raw) else os.path.join(cwd, raw)
        )
        if not os.path.isfile(abs_path):
            continue
        try:
            with open(abs_path, errors="replace") as f:
                content = f.read(MAX_FILE_BYTES)
            if len(content) >= MAX_FILE_BYTES:
                content += "\n... [file truncated]"
            resolved.append((raw, abs_path, content))
        except OSError:
            continue

    if not resolved:
        return text, []

    sections = [text, "\n\n---\n**Attached files:**"]
    for display, abs_path, content in resolved:
        ext  = os.path.splitext(abs_path)[1].lower()
        lang = _EXT_LANG.get(ext, "")
        lines = content.count("\n") + 1
        sections.append(f"\n### {display}  ({lines} lines)\n```{lang}\n{content}\n```")

    return "\n".join(sections), [r[1] for r in resolved]

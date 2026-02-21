#!/usr/bin/env python3
"""
collab — Claude Code + Codex CLI orchestrator

Usage:
  collab "Build a FastAPI REST API with JWT authentication"
  collab --claude "Explain /src/auth.py"
  collab --codex  "Generate CRUD boilerplate"
  collab --parallel "Compare approaches for OAuth2"
  collab --plan-only "Design a microservice system"
  collab -i
  collab research "Improve Pixel AP on MVTec by 5%"
  collab sessions / collab resume
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

import yaml

from agent_collab.agents import ClaudeAgent, CodexAgent
from agent_collab.agents.base import AgentResult
from agent_collab.file_ref import expand_file_refs

CONFIG_PATH = Path(__file__).parent / "config.yaml"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_USE_COLOR = sys.stdout.isatty()


# ─── Colors ───────────────────────────────────────────────────────────────────
def _c(text: str, *styles: str) -> str:
    if not _USE_COLOR:
        return text
    codes = {
        "reset": "\033[0m",  "bold":    "\033[1m",  "dim":     "\033[2m",
        "cyan":  "\033[96m", "green":   "\033[92m", "yellow":  "\033[93m",
        "red":   "\033[91m", "magenta": "\033[95m", "blue":    "\033[94m",
        "white": "\033[97m",
    }
    return "".join(codes.get(s, "") for s in styles) + text + codes["reset"]


# ─── File attachment helper ────────────────────────────────────────────────────
def _attach_files(text: str, cwd: str) -> str:
    """Expand /file and @file refs, print notice, return expanded text."""
    expanded, attached = expand_file_refs(text, cwd)
    if attached:
        names = [os.path.basename(p) for p in attached]
        print(_c(f"  📎 {len(attached)} file(s) attached: {', '.join(names)}", "dim"))
    return expanded


# ─── Syntax highlighting ───────────────────────────────────────────────────────
_LANG_COLORS: dict[str, str] = {
    "python":     "\033[38;5;81m",
    "javascript": "\033[38;5;220m", "js":  "\033[38;5;220m",
    "typescript": "\033[38;5;75m",  "ts":  "\033[38;5;75m",
    "bash":       "\033[38;5;114m", "sh":  "\033[38;5;114m",
    "json":       "\033[38;5;183m",
    "yaml":       "\033[38;5;215m", "yml": "\033[38;5;215m",
    "sql":        "\033[38;5;204m",
    "rust":       "\033[38;5;166m",
    "go":         "\033[38;5;159m",
    "cpp":        "\033[38;5;105m", "c":   "\033[38;5;105m",
}


def _highlight_output(text: str) -> str:
    """Colorize code blocks and markdown in terminal output."""
    if not _USE_COLOR:
        return text
    import re

    def _sub_block(m: re.Match) -> str:
        lang = m.group(1).strip().lower()
        code = m.group(2)
        color = _LANG_COLORS.get(lang, "\033[37m")
        dim, reset = "\033[2m", "\033[0m"
        return f"{dim}```{m.group(1)}{reset}\n{color}{code}{reset}{dim}```{reset}"

    text = re.sub(r"```(\w*)\n(.*?)```", _sub_block, text, flags=re.DOTALL)
    # Bold **text** and headers
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: _c(m.group(1), "bold"), text)
    text = re.sub(
        r"^(#{1,3} .+)$",
        lambda m: _c(m.group(1), "bold"),
        text,
        flags=re.MULTILINE,
    )
    return text


def _print_highlighted(text: str, compact: bool = False) -> None:
    """Print agent output with syntax highlighting and optional line limit."""
    highlighted = _highlight_output(text.strip())
    lines = highlighted.splitlines()
    limit = 25 if compact else None
    for line in (lines[:limit] if limit else lines):
        print(f"  {line}")
    if limit and len(lines) > limit:
        print(_c(f"  ╌╌ +{len(lines) - limit} more lines ╌╌", "dim"))


# ─── REPL context (conversation history) ──────────────────────────────────────
class _ReplCtx:
    """Tracks conversation history and settings for the interactive REPL."""

    def __init__(self) -> None:
        self.history: list[tuple[str, str]] = []   # (user_prompt, agent_response)
        self.compact: bool = False
        self.last_output: str = ""

    def push(self, prompt: str, response: str) -> None:
        self.history.append((prompt[:600], response[:1500]))
        self.last_output = response
        if len(self.history) > 8:
            self.history.pop(0)

    def inject_context(self, prompt: str) -> str:
        """Prepend the last 3 interactions as context."""
        if not self.history:
            return prompt
        recent = self.history[-3:]
        lines = ["--- Conversation context ---"]
        for p, r in recent:
            r_trim = r[:500] + ("..." if len(r) > 500 else "")
            lines.append(f"User: {p}\nAssistant: {r_trim}")
        lines.append("--- Current request ---")
        return "\n\n".join(lines) + "\n" + prompt

    def token_estimate(self) -> int:
        chars = sum(len(p) + len(r) for p, r in self.history)
        return chars // 4


def _interactive_file_select(text: str, pattern: str, cwd: str) -> Optional[tuple[str, str]]:
    """
    Show interactive file selector when Tab is pressed on @pattern or /pattern.
    Returns (before_pattern, selected_file) or None if cancelled.
    """
    from agent_collab.file_ref import list_file_candidates

    # Determine search pattern
    if pattern.startswith("@"):
        search = pattern[1:]
        prefix = "@"
    elif pattern.startswith("/"):
        search = pattern
        prefix = ""
    else:
        return None

    # Get candidates
    candidates = list_file_candidates(search, cwd) if search else []

    if not candidates:
        return None

    if len(candidates) == 1:
        # Only one match - auto-complete
        selected = prefix + candidates[0] if prefix else candidates[0]
        # Find pattern in text and get the part before it
        import re
        match = re.search(r'(@\S+\?*|/\S+\?*)$', text)
        if match:
            before = text[:match.start()]
            return (before, selected)
        return (text, selected)

    # Multiple matches - show selection menu
    print(_c("\n  📁 Select a file (or Esc to cancel):", "cyan", "bold"))
    for i, path in enumerate(candidates, 1):
        filename = os.path.basename(path)
        dirname = os.path.dirname(path)
        dir_str = _c(f"{dirname}/", "dim") if dirname else ""
        print(f"    {_c(str(i), 'yellow', 'bold'):>3}. {dir_str}{_c(filename, 'green')}")

    print()
    try:
        choice = input(_c("  Enter number (1-{}) or Esc: ".format(len(candidates)), "cyan"))
        choice = choice.strip()

        if not choice or choice.lower() in ("esc", "q", "cancel"):
            return None

        idx = int(choice) - 1
        if 0 <= idx < len(candidates):
            selected = candidates[idx]
            selected_path = prefix + selected if prefix else selected
            # Find pattern in text and get the part before it
            import re
            match = re.search(r'(@\S+\?*|/\S+\?*)$', text)
            if match:
                before = text[:match.start()]
                return (before, selected_path)
            return (text, selected_path)
    except (ValueError, KeyboardInterrupt, EOFError):
        pass

    return None


# ─── Multi-line input ──────────────────────────────────────────────────────────
def _multiline_input(prompt_str: str, cwd: str = ".") -> str:
    """
    Read one line, or a multi-line block when the line starts with \"\"\".
    Supports interactive file selection with @pattern?.
    End multi-line mode with \"\"\" on its own line or Ctrl+D.
    Ctrl+C clears current input and returns empty string.
    Ctrl+D exits collab.
    """
    # Print prompt on separate line to avoid line wrapping issues with long input
    print(prompt_str, end='', flush=True)
    try:
        first = input()
    except KeyboardInterrupt:
        # Ctrl+C pressed - clear input and return empty
        print()
        return ""
    except EOFError:
        # Ctrl+D pressed - exit collab (propagate to caller)
        raise

    # Check for file reference pattern
    # If line ends with @something? or /something?, offer interactive selection
    import re
    file_pattern = re.search(r'(@\S+\?+|/\S+\?+)$', first)
    if file_pattern:
        # User typed @pattern? or /pattern? - trigger interactive selection
        pattern = file_pattern.group(1).rstrip('?')
        result = _interactive_file_select(first, pattern, cwd)
        if result:
            before, selected_file = result
            # Show the updated prompt and let user continue editing
            updated = before + selected_file
            print(_c(f"\n  ✓ Selected: {selected_file}", "green"))
            print(_c("  Continue editing (or press Enter to submit):", "dim"))

            # Use readline to pre-fill the input with the updated text
            try:
                import readline
                def prefill_hook():
                    readline.insert_text(updated)
                    readline.redisplay()
                readline.set_pre_input_hook(prefill_hook)
                print(prompt_str, end='', flush=True)
                first = input()
                readline.set_pre_input_hook()  # Clear the hook
            except KeyboardInterrupt:
                # Ctrl+C after file selection - clear input
                print()
                return ""
            except (ImportError, AttributeError):
                # Readline not available - just show and ask for continuation
                print(f"  Current: {updated}")
                print(_c("  Add more (or Enter to submit): ", "dim"), end='', flush=True)
                try:
                    continuation = input()
                    if continuation.strip():
                        first = updated + " " + continuation
                    else:
                        first = updated
                except KeyboardInterrupt:
                    print()
                    return ""

    if not first.startswith('"""'):
        return first.strip()

    lines = [first[3:]]
    print(_c('  (multi-line — end with """ on a blank line, Ctrl+C to cancel)', "dim"))
    while True:
        try:
            line = input(_c("  … ", "dim"))
        except KeyboardInterrupt:
            # Ctrl+C in multi-line mode - cancel and clear
            print(_c("\n  Input cancelled", "dim"))
            return ""
        except EOFError:
            break
        if line.strip() == '"""':
            break
        lines.append(line)
    return "\n".join(lines).strip()


# ─── Clipboard ─────────────────────────────────────────────────────────────────
def _copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard. Returns True on success."""
    import subprocess
    for cmd in (
        ["pbcopy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
        ["wl-copy"],
    ):
        try:
            proc = subprocess.run(cmd, input=text.encode(), capture_output=True, timeout=3)
            if proc.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return False


# ─── Config / agents ──────────────────────────────────────────────────────────
def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def build_agents(cfg: dict) -> tuple[ClaudeAgent, CodexAgent]:
    cc = cfg["agents"]["claude"]
    cx = cfg["agents"]["codex"]
    return (
        ClaudeAgent(
            permission_mode=cc.get("permission_mode", "bypassPermissions"),
            extra_args=cc.get("extra_args", []),
        ),
        CodexAgent(extra_args=cx.get("extra_args", [])),
    )


# ─── Single / Parallel agent modes (non-REPL) ─────────────────────────────────
def run_single(agent, task: str, cwd: str) -> None:
    task = _attach_files(task, cwd)
    done = threading.Event()
    label = _c(agent.name.upper(), "cyan" if agent.name == "claude" else "green", "bold")

    def _spin():
        i = 0
        while not done.is_set():
            sys.stderr.write(f"\r{SPINNER[i % len(SPINNER)]}  [{label}] thinking...")
            sys.stderr.flush()
            time.sleep(0.1)
            i += 1
        sys.stderr.write("\r" + " " * 50 + "\r")
        sys.stderr.flush()

    spin_t = threading.Thread(target=_spin, daemon=True)
    spin_started = sys.stderr.isatty()
    if spin_started:
        spin_t.start()
    result: AgentResult = agent.run(task, cwd=cwd)
    done.set()
    if spin_started:
        spin_t.join(timeout=0.5)

    if not result.success:
        print(_c(f"[{agent.name.upper()} ERROR]", "red", "bold"))
        print(result.error)
        sys.exit(1)
    print(result.display(color=_USE_COLOR))


def run_parallel(claude: ClaudeAgent, codex: CodexAgent, task: str, cwd: str) -> None:
    task = _attach_files(task, cwd)
    results: list[AgentResult] = []
    threads = [
        claude.run_async(task, cwd=cwd, results=results),
        codex.run_async(task, cwd=cwd, results=results),
    ]
    done = threading.Event()

    def _spin():
        i = 0
        while not done.is_set():
            sys.stderr.write(
                f"\r{SPINNER[i % len(SPINNER)]}  Running Claude + Codex in parallel... ({len(results)}/2 done)"
            )
            sys.stderr.flush()
            time.sleep(0.1)
            i += 1
        sys.stderr.write("\r" + " " * 70 + "\r")
        sys.stderr.flush()

    spin_t = threading.Thread(target=_spin, daemon=True)
    if sys.stderr.isatty():
        spin_t.start()
    for t in threads:
        t.join(timeout=120)
    done.set()
    spin_t.join(timeout=0.5)
    results.sort(key=lambda r: 0 if r.agent_name == "claude" else 1)
    for r in results:
        print(r.display(color=_USE_COLOR))

    # ── Critic pass ───────────────────────────────────────────────────────────
    successful = [r for r in results if r.success and r.output.strip()]
    if len(successful) >= 1:
        combined = "\n\n".join(
            f"=== {r.agent_name.upper()} ===\n{r.output.strip()}" for r in successful
        )
        critic_prompt = (
            f"You are a rigorous critic reviewing parallel agent responses.\n\n"
            f"TASK: {task}\n\n{combined}\n\n"
            "Critically evaluate:\n"
            "1. **Correctness**: Any factual errors or faulty logic?\n"
            "2. **Completeness**: What important aspects were missed?\n"
            "3. **Contradictions**: Where agents disagree — which is right?\n"
            "4. **Best Approach**: Which response should be acted on?\n"
            "5. **Improvements**: What would make the answer stronger?\n\n"
            "Be specific, constructive, and concise."
        )
        print(_c("\n── Critic [CLAUDE] ─────────────────────────────────────────────────", "red", "bold"))
        done2 = threading.Event()

        def _spin2():
            i = 0
            while not done2.is_set():
                sys.stderr.write(f"\r{SPINNER[i % len(SPINNER)]}  [{_c('CRITIC', 'red')}] reviewing...")
                sys.stderr.flush()
                time.sleep(0.1)
                i += 1
            sys.stderr.write("\r" + " " * 50 + "\r")
            sys.stderr.flush()

        spin2_t = threading.Thread(target=_spin2, daemon=True)
        spin2_started = sys.stderr.isatty()
        if spin2_started:
            spin2_t.start()
        critic_result = claude.run(critic_prompt, cwd=cwd)
        done2.set()
        if spin2_started:
            spin2_t.join(timeout=0.5)
        print(critic_result.display(color=_USE_COLOR))


# ─── Goal-driven planning mode ────────────────────────────────────────────────
def run_goal(goal: str, cwd: str, claude: ClaudeAgent, codex: CodexAgent,
             plan_only: bool = False) -> None:
    from agent_collab.planner import generate_plan
    from agent_collab.plan_ui import edit_plan, print_plan
    from agent_collab.executor import execute_plan

    goal = _attach_files(goal, cwd)
    print(_c(f"\n⚙  Generating plan for: {goal[:120]}", "bold"))
    done = threading.Event()

    def _spin():
        i = 0
        while not done.is_set():
            sys.stderr.write(f"\r{SPINNER[i % len(SPINNER)]}  Planning...")
            sys.stderr.flush()
            time.sleep(0.1)
            i += 1
        sys.stderr.write("\r" + " " * 30 + "\r")
        sys.stderr.flush()

    spin_t = threading.Thread(target=_spin, daemon=True)
    spin_started = sys.stderr.isatty()
    if spin_started:
        spin_t.start()
    try:
        plan = generate_plan(goal, cwd)
    except KeyboardInterrupt:
        # User cancelled with Ctrl+C - return gracefully
        done.set()
        if spin_started:
            spin_t.join(timeout=0.5)
        return
    except Exception as e:
        done.set()
        if spin_started:
            spin_t.join(timeout=0.5)
        print(_c(f"\nPlanning failed: {e}", "red"))
        sys.exit(1)
    done.set()
    if spin_started:
        spin_t.join(timeout=0.5)

    final_plan = edit_plan(plan)
    if final_plan is None:
        print(_c("Cancelled.", "dim"))
        return
    if plan_only:
        print_plan(final_plan, verbose=True)
        return

    from agent_collab.session_store import new_planning_session
    session = new_planning_session(goal, cwd, final_plan)
    print(_c(f"Session saved → {session.id}", "dim"))
    execute_plan(final_plan, cwd=cwd, claude=claude, codex=codex, session=session)


# ─── Interactive REPL ─────────────────────────────────────────────────────────
_HELP_COMMANDS = [
    ("/help",            "Show this help"),
    ("/clear",           "Clear screen and conversation history"),
    ("/history",         "Show recent conversation history"),
    ("/status",   "/s", "Show session info (cwd, context, tokens)"),
    ("/compact",         "Toggle compact output mode (25-line preview)"),
    ("/copy",            "Copy last agent output to clipboard"),
    ("/files <pattern>", "Find files matching pattern"),
    ("@?<pattern>",      "Quick file search (alias for /files)"),
    ("",                 ""),
    ("/claude <task>",   "Force Claude Code for this task"),
    ("/codex <task>",    "Force Codex CLI for this task"),
    ("/parallel <t>",   "Run both agents + critic simultaneously"),
    ("/plan <goal>",     "Generate plan without executing"),
    ("/research <goal>", "AI research mode (6-step iterative loop)"),
    ("/quit",            "Exit"),
]


def _print_help() -> None:
    print()
    print(_c("━" * 65, "cyan"))
    print()
    print(_c("  📖 agent-collab Commands & Help", "cyan", "bold"))
    print()
    print(_c("━" * 65, "cyan"))
    print()

    # Basic Usage
    print(_c("  🚀 Getting Started:", "bold"))
    print(_c("     Just type what you want:", "dim"))
    print(_c("       ▶ Build a FastAPI server with JWT auth", "green"))
    print(_c("       ▶ Review @auth.py and fix security issues", "green"))
    print()

    # Agent Commands
    print(_c("  🤖 Agent Commands:", "bold"))
    for cmd, desc in [
        ("/claude <task>", "Use Claude Code for complex reasoning & analysis"),
        ("/codex <task>", "Use Codex for quick code generation"),
        ("/parallel <task>", "Run both agents + get critic review"),
        ("/plan <goal>", "Generate execution plan (preview only)"),
        ("/research <goal>", "AI research mode (6-step iterative loop)"),
        ("research <goal>", "Same as /research (keyword shortcut)"),
    ]:
        print(_c(f"     {cmd:20}", "yellow") + _c(f"  {desc}", "dim"))
    print()

    # File Operations
    print(_c("  📁 File Operations:", "bold"))
    for cmd, desc in [
        ("@file.py", "Attach file content to your request"),
        ("@pattern?", "Interactive file picker (select from list)"),
        ("@?pattern", "Search for files matching pattern"),
        ("/files <pattern>", "Find and list matching files"),
        ("Tab", "Autocomplete file paths"),
    ]:
        print(_c(f"     {cmd:20}", "yellow") + _c(f"  {desc}", "dim"))
    print()

    # Session Management
    print(_c("  💾 Session & History:", "bold"))
    for cmd, desc in [
        ("/history", "Show recent conversation"),
        ("/status", "Show session info & token count"),
        ("/clear", "Clear screen & conversation history"),
        ("/copy", "Copy last response to clipboard"),
    ]:
        print(_c(f"     {cmd:20}", "yellow") + _c(f"  {desc}", "dim"))
    print()

    # Utilities
    print(_c("  ⚙️  Utilities:", "bold"))
    for cmd, desc in [
        ("/compact", "Toggle compact output mode"),
        ("/help", "Show this help message"),
        ("/quit", "Exit interactive mode"),
    ]:
        print(_c(f"     {cmd:20}", "yellow") + _c(f"  {desc}", "dim"))
    print()

    # Tips
    print(_c("  💡 Pro Tips:", "bold"))
    tips = [
        'Multi-line input: Start with """ and end with """',
        "File selection: @main? shows files, pick by number",
        "Quick execute: Just describe your goal naturally!",
        "Context aware: Previous messages inform new requests",
        "Ctrl+C: Clear current input and start fresh",
        "Ctrl+D: Exit collab",
    ]
    for tip in tips:
        print(_c(f"     • {tip}", "dim"))
    print()
    print(_c("━" * 65, "cyan"))
    print()


def _print_history(ctx: _ReplCtx) -> None:
    if not ctx.history:
        print(_c("  No history yet.", "dim"))
        return
    print()
    for i, (p, r) in enumerate(ctx.history, 1):
        p_disp = (p[:80] + "…") if len(p) > 80 else p
        r_disp = (r[:120] + "…") if len(r) > 120 else r
        print(_c(f"  [{i}]", "yellow", "bold") + f"  {_c('You:', 'bold')} {p_disp}")
        print(_c(f"       AI: ", "dim") + _c(r_disp, "dim"))
        print()


def _print_status(ctx: _ReplCtx, cwd: str) -> None:
    tok = ctx.token_estimate()
    print()
    print(_c("  ── Session Status ─────────────────────────────", "cyan"))
    print(f"  {'CWD':<14} {cwd}")
    print(f"  {'History':<14} {len(ctx.history)} interaction(s)")
    print(f"  {'Context ~':<14} {tok:,} tokens")
    print(f"  {'Compact':<14} {'on' if ctx.compact else 'off'}")
    if ctx.last_output:
        print(f"  {'Last output':<14} {len(ctx.last_output):,} chars — /copy to clipboard")
    print(_c("  ───────────────────────────────────────────────", "cyan"))
    print()


def _setup_file_completion(cwd: str) -> None:
    """Enable readline tab-completion for / paths and @name references."""
    try:
        import readline
        import glob as _glob

        # Store matches for interactive selection
        _completion_matches = []

        def _completer(text: str, state: int) -> Optional[str]:
            nonlocal _completion_matches

            if state == 0:  # First call - generate matches
                _completion_matches = []

                if text.startswith("/"):
                    matches = [
                        (m + "/" if os.path.isdir(m) else m)
                        for m in _glob.glob(text + "*")
                    ]
                    _completion_matches = matches
                elif text.startswith("@"):
                    name = text[1:]
                    hits = _glob.glob(os.path.join(cwd, "**", name + "*"), recursive=True)
                    matches = ["@" + os.path.relpath(h, cwd) for h in hits if os.path.isfile(h)]
                    _completion_matches = matches[:20]  # Limit to 20 for display
                else:
                    return None

            return _completion_matches[state] if state < len(_completion_matches) else None

        readline.set_completer(_completer)
        readline.set_completer_delims(" \t\n;")
        readline.parse_and_bind("tab: complete")

        # Make Tab show all matches at once instead of cycling
        readline.parse_and_bind("set show-all-if-ambiguous on")
        readline.parse_and_bind("set completion-display-width 1")

    except (ImportError, AttributeError):
        pass


def _run_agent_repl(agent, task: str, cwd: str, ctx: _ReplCtx) -> None:
    """Run agent in REPL mode: attach files, inject history, capture output."""
    raw_task = task
    task = _attach_files(task, cwd)
    task_with_ctx = ctx.inject_context(task)

    done = threading.Event()
    color = "cyan" if agent.name == "claude" else "green"
    label = _c(agent.name.upper(), color, "bold")

    def _spin():
        i = 0
        while not done.is_set():
            sys.stderr.write(f"\r{SPINNER[i % len(SPINNER)]}  [{label}] thinking...")
            sys.stderr.flush()
            time.sleep(0.1)
            i += 1
        sys.stderr.write("\r" + " " * 50 + "\r")
        sys.stderr.flush()

    spin_t = threading.Thread(target=_spin, daemon=True)
    spin_started = sys.stderr.isatty()
    if spin_started:
        spin_t.start()
    result: AgentResult = agent.run(task_with_ctx, cwd=cwd)
    done.set()
    if spin_started:
        spin_t.join(timeout=0.5)

    if not result.success:
        print(_c(f"\n  ✖ [{agent.name.upper()} ERROR]", "red", "bold"))
        print(_c(f"  {result.error[:300]}", "red"))
        return

    t_str = _c(f"{result.duration_s:.1f}s", "dim")
    print(_c(f"\n  ✓ [{agent.name.upper()}]", color, "bold") + f"  {t_str}")
    print(_c("  " + "┄" * 30, "dim"))
    _print_highlighted(result.output, compact=ctx.compact)
    print()
    ctx.push(raw_task, result.output)


def _show_file_candidates(pattern: str, cwd: str) -> None:
    """Show file candidates matching the pattern."""
    from agent_collab.file_ref import list_file_candidates
    import os

    if not pattern:
        print(_c("  📁 File Search", "cyan", "bold"))
        print(_c("  Usage: /files <pattern>  or  @?<pattern>", "dim"))
        print(_c("  Examples:", "dim"))
        print(_c("    /files auth       → find files with 'auth' in name", "dim"))
        print(_c("    @?test           → find test files", "dim"))
        print(_c("    /files *.py      → find all Python files", "dim"))
        print()
        return

    candidates = list_file_candidates(pattern, cwd)

    if not candidates:
        print(_c(f"  ✖ No files found matching '{pattern}'", "red"))
        return

    print(_c(f"  📁 Found {len(candidates)} file(s) matching '{pattern}':", "cyan", "bold"))
    print()

    # Group by directory
    by_dir: dict[str, list[str]] = {}
    for path in candidates:
        dirname = os.path.dirname(path) or "."
        if dirname not in by_dir:
            by_dir[dirname] = []
        by_dir[dirname].append(os.path.basename(path))

    # Sort directories
    for dirname in sorted(by_dir.keys()):
        files = by_dir[dirname]
        dir_display = _c(f"{dirname}/", "blue", "bold") if dirname != "." else _c("./", "blue", "bold")
        print(f"  {dir_display}")

        for filename in sorted(files):
            # Highlight the pattern in filename
            if pattern and pattern != "*":
                idx = filename.lower().find(pattern.lower())
                if idx != -1:
                    before = filename[:idx]
                    match = filename[idx:idx+len(pattern)]
                    after = filename[idx+len(pattern):]
                    display = before + _c(match, "yellow", "bold") + after
                else:
                    display = filename
            else:
                display = filename

            full_path = os.path.join(dirname, filename)
            # Show file size
            try:
                size = os.path.getsize(os.path.join(cwd, full_path))
                if size < 1024:
                    size_str = f"{size}B"
                elif size < 1024 * 1024:
                    size_str = f"{size/1024:.1f}KB"
                else:
                    size_str = f"{size/(1024*1024):.1f}MB"
                size_display = _c(f"({size_str})", "dim")
            except:
                size_display = ""

            # Show reference syntax
            ref = _c(f"@{filename}", "green") if dirname == "." else _c(f"{full_path}", "green")
            print(f"    {display:40} {size_display:12} → {ref}")

        print()

    print(_c(f"  💡 Use @filename or /path to reference files in your prompt", "dim"))
    print()


def interactive_loop(claude: ClaudeAgent, codex: CodexAgent, cwd: str) -> None:
    _setup_file_completion(cwd)
    ctx = _ReplCtx()

    # ── Welcome Banner ────────────────────────────────────────────────────────
    print()
    print(_c("━" * 65, "cyan"))
    print()
    print(_c("  🤖 agent-collab", "cyan", "bold") + _c("  │  Claude Code ↔ Codex CLI", "cyan"))
    print(_c("  Interactive AI Collaboration Mode", "cyan", "dim"))
    print()
    print(_c("━" * 65, "cyan"))
    print()

    # Quick Start Guide
    print(_c("  ✨ Quick Start:", "bold"))
    print(_c("     Just describe what you want to build, and we'll handle the rest!", "dim"))
    print()
    print(_c("  💡 Examples:", "bold"))
    print(_c("     ▶ ", "dim") + _c("Build a REST API with authentication", "green"))
    print(_c("     ▶ ", "dim") + _c("Review @main.py and suggest improvements", "green"))
    print(_c("     ▶ ", "dim") + _c("/claude Explain how this codebase works", "green"))
    print(_c("     ▶ ", "dim") + _c("research Improve Pixel AP by 5%", "green") + _c(" (AI research mode)", "dim"))
    print()

    # Feature Highlights
    print(_c("  🎯 Features:", "bold"))
    print(_c("     • ", "dim") + _c("@file.py", "yellow") + _c(" - attach files to your request", "dim"))
    print(_c("     • ", "dim") + _c("@pattern?", "yellow") + _c(" - interactive file picker", "dim"))
    print(_c("     • ", "dim") + _c("/help", "yellow") + _c(" - show all commands", "dim"))
    print(_c("     • ", "dim") + _c("Tab", "yellow") + _c(" - autocomplete file paths", "dim"))
    print(_c("     • ", "dim") + _c("Ctrl+C", "yellow") + _c(" - clear current input", "dim"))
    print(_c("     • ", "dim") + _c("Ctrl+D", "yellow") + _c(" - exit collab", "dim"))
    print()
    print(_c("━" * 65, "cyan"))
    print()

    while True:
        # ── Build friendly prompt with context ─────────────────────────────
        tok = ctx.token_estimate()
        prefix = ""
        if ctx.compact:
            prefix += _c("[compact] ", "dim")
        if tok > 0:
            prefix += _c(f"[~{tok}t] ", "dim")

        # Friendly prompt with hint on first use
        if not ctx.history:
            prompt_str = prefix + _c("▶ ", "green", "bold") + _c("(Type your request or /help) ", "dim")
        else:
            prompt_str = prefix + _c("▶ ", "green", "bold")

        try:
            raw = _multiline_input(prompt_str, cwd)
        except EOFError:
            # Ctrl+D pressed - exit
            print()
            print(_c("  Bye!", "dim"))
            break
        except KeyboardInterrupt:
            # Rare case - usually handled in _multiline_input
            print()
            break

        if not raw:
            continue
        if raw in ("/quit", "/exit", "quit", "exit"):
            print(_c("Bye!", "dim"))
            break

        # ── Slash commands ─────────────────────────────────────────────────
        if raw == "/help":
            _print_help()

        elif raw == "/clear":
            os.system("clear" if os.name != "nt" else "cls")
            ctx.history.clear()
            ctx.last_output = ""
            print(_c("  Context cleared.", "dim"))

        elif raw == "/history":
            _print_history(ctx)

        elif raw in ("/status", "/s"):
            _print_status(ctx, cwd)

        elif raw == "/compact":
            ctx.compact = not ctx.compact
            print(_c(f"  Compact mode: {'on' if ctx.compact else 'off'}", "dim"))

        elif raw == "/copy":
            if not ctx.last_output:
                print(_c("  Nothing to copy yet.", "dim"))
            elif _copy_to_clipboard(ctx.last_output):
                print(_c(f"  ✓ Copied {len(ctx.last_output):,} chars to clipboard.", "dim"))
            else:
                print(_c("  ✖ Clipboard unavailable (install xclip / xsel / pbcopy).", "red"))

        # ── Agent routing ──────────────────────────────────────────────────
        elif raw.startswith("/claude "):
            _run_agent_repl(claude, raw[8:].strip(), cwd, ctx)

        elif raw.startswith("/codex "):
            _run_agent_repl(codex, raw[7:].strip(), cwd, ctx)

        elif raw.startswith("/parallel "):
            task = raw[10:].strip()
            run_parallel(claude, codex, task, cwd)

        elif raw.startswith("/plan "):
            run_goal(raw[6:].strip(), cwd, claude, codex, plan_only=True)

        elif raw.startswith("/research "):
            # /research "goal" → research mode
            goal = raw[10:].strip()
            run_research([goal, "--cwd", cwd])

        elif raw.startswith("/files"):
            # Show file candidates
            pattern = raw[6:].strip() if len(raw) > 6 else ""
            _show_file_candidates(pattern, cwd)

        elif raw.startswith("@?") or raw.startswith("/?"):
            # Quick file lookup: @?pattern or /?pattern
            pattern = raw[2:].strip()
            _show_file_candidates(pattern, cwd)

        elif raw.startswith("/"):
            unknown_cmd = raw.split()[0]
            print(_c(f"  ❌ Unknown command: '{unknown_cmd}'", "red"))
            print(_c(f"  💡 Tip: Type /help to see all available commands", "yellow"))
            print(_c(f"  💡 Or just describe what you want without a /command prefix!", "yellow"))
            print()

        # ── Research mode (keyword-based) ──────────────────────────────────
        elif raw.lower().startswith("research "):
            # research "goal" → research mode (without slash)
            goal = raw[9:].strip()
            run_research([goal, "--cwd", cwd])

        # ── Goal → Plan → Execute ──────────────────────────────────────────
        else:
            run_goal(raw, cwd, claude, codex)


# ─── Research subcommand ──────────────────────────────────────────────────────
def run_research(argv: list[str]) -> None:
    from agent_collab.research.research_mode import main as research_main
    research_main(argv)


# ─── Resume subcommand ────────────────────────────────────────────────────────
def run_resume(argv: list[str], claude: ClaudeAgent, codex: CodexAgent) -> None:
    from agent_collab.resume_ui import pick_session
    from agent_collab.executor import execute_plan
    from agent_collab.plan_ui import print_plan

    session_id = argv[0] if argv else None
    session = pick_session(session_id)
    if session is None:
        return

    print()
    print(_c(f"Resuming: {session.goal}", "bold"))
    print(_c(f"Type: {session.type}  |  Status: {session.status}  |  {session.progress_label()}", "dim"))

    if session.type == "planning":
        if not session.plan:
            print(_c("No plan found in session.", "red"))
            return
        done_ids = session.completed_task_ids
        total = len(session.plan.get("tasks", []))
        remaining = total - len(done_ids)

        if session.status == "completed":
            print(_c("This session is already completed.", "green"))
            print_plan(session.plan)
            return

        if done_ids:
            print(_c(f"\n✓ Tasks already done: {done_ids}", "green"))
        print(_c(f"→ Running {remaining} remaining task(s)...\n", "yellow"))

        execute_plan(
            session.plan, cwd=session.cwd,
            claude=claude, codex=codex,
            session=session, skip_task_ids=done_ids,
        )

    elif session.type == "research":
        if not session.research_state_path:
            print(_c("No research state path found in session.", "red"))
            return
        run_research([
            "--resume", session.research_state_path,
            "--rounds", str(session.total_rounds),
            "--cwd", session.cwd,
        ])


# ─── Log check subcommand ─────────────────────────────────────────────────────
def run_log_check(args: list[str]) -> None:
    """Check experiment logs - shortcut for research/check_log.py"""
    from agent_collab.research.monitor import show_log_tail, print_log_summary
    from pathlib import Path

    if not args or args[0] in ("-h", "--help"):
        print(_c("\nUsage: collab log <log_file> [options]", "bold"))
        print("\nQuickly check experiment logs")
        print("\nOptions:")
        print("  -t, --tail N     Show last N lines (filtered for important info)")
        print("  -f, --full       Show all lines (unfiltered)")
        print("  --no-filter      Don't filter tail output")
        print("  --no-color       Disable colors")
        print("\nExamples:")
        print(_c("  collab log logs/exp1/training.log", "dim"))
        print(_c("  collab log logs/exp1/training.log -t 50", "dim"))
        print(_c("  collab log logs/exp1/training.log --full", "dim"))
        print()
        return

    log_file = args[0]
    log_path = Path(log_file)

    if not log_path.exists():
        print(_c(f"Error: Log file not found: {log_path}", "red"))
        return

    # Parse options
    show_tail = False
    tail_lines = 20
    filter_important = True
    colorize = True

    i = 1
    while i < len(args):
        arg = args[i]
        if arg in ("-t", "--tail"):
            show_tail = True
            if i + 1 < len(args) and args[i + 1].isdigit():
                tail_lines = int(args[i + 1])
                i += 1
        elif arg in ("-f", "--full"):
            # Show full file
            try:
                with open(log_path, "r") as f:
                    print(f.read())
            except Exception as e:
                print(_c(f"Error reading log: {e}", "red"))
            return
        elif arg == "--no-filter":
            filter_important = False
        elif arg == "--no-color":
            colorize = False
        i += 1

    if show_tail:
        show_log_tail(log_path, lines=tail_lines, filter_important=filter_important, colorize=colorize)
    else:
        # Default: show summary
        print_log_summary(log_path)
        print(_c("\n💡 Tip: Use 'collab log <file> -t N' to see last N lines", "dim"))


# ─── Sessions list subcommand ─────────────────────────────────────────────────
def run_sessions() -> None:
    from agent_collab.session_store import list_sessions
    from agent_collab.resume_ui import _c as _rc, _fmt_session

    sessions = list_sessions()
    if not sessions:
        print(_c("No saved sessions found.", "dim"))
        return
    print()
    print(_c(f"{'#':>4}  {'Type':10}  {'Updated':16}  {'Goal':55}  {'Progress':12}  Status", "bold"))
    print("  " + "─" * 110)
    for i, s in enumerate(sessions, 1):
        print(_fmt_session(i, s))
    print()
    print(_c(f"  {len(sessions)} session(s) found. Run `collab resume` to select one.", "dim"))


# ─── Main entry point ─────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] == "research":
        run_research(argv[1:])
        return

    if argv and argv[0] in ("sessions", "ls"):
        run_sessions()
        return

    if argv and argv[0] == "log":
        run_log_check(argv[1:])
        return

    parser = argparse.ArgumentParser(
        prog="collab",
        description="Claude Code + Codex CLI orchestrator\n\n"
                    "Default mode: Interactive REPL (just run 'collab' with no arguments)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("goal", nargs="*", help="Development goal or task (omit for interactive mode)")
    parser.add_argument("--claude",      action="store_true", help="Force Claude Code")
    parser.add_argument("--codex",       action="store_true", help="Force Codex CLI")
    parser.add_argument("--parallel",    action="store_true", help="Run both agents simultaneously")
    parser.add_argument("--plan-only",   action="store_true", help="Generate plan without executing")
    parser.add_argument("--resume",      nargs="?", const="PICKER", default=None,
                       help="Resume a session (shows picker if no session-id given)")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive REPL mode (default if no goal)")
    parser.add_argument("--cwd",         default=".", help="Working directory for agents")
    parser.add_argument("--verbose",     "-v", action="store_true")

    args = parser.parse_args(argv)
    cfg = load_config()
    claude, codex = build_agents(cfg)
    cwd = os.path.abspath(args.cwd)

    # Handle special "resume" command (legacy syntax)
    if argv and argv[0] == "resume":
        run_resume(argv[1:], claude, codex)
        return

    # Handle --resume flag
    if args.resume is not None:
        if args.resume == "PICKER":
            # Show interactive picker
            run_resume([], claude, codex)
        else:
            # Resume specific session
            run_resume([args.resume], claude, codex)
        return

    # Default to interactive mode if no goal provided
    if not args.goal or args.interactive:
        # Show hint if explicitly running without arguments
        if not argv:
            print(_c("  💡 Tip: Just type 'collab' to start interactive mode (this is the default!)", "dim"))
            print()
        interactive_loop(claude, codex, cwd)
        return

    goal = " ".join(args.goal)

    if args.claude:
        run_single(claude, goal, cwd)
    elif args.codex:
        run_single(codex, goal, cwd)
    elif args.parallel:
        run_parallel(claude, codex, goal, cwd)
    else:
        run_goal(goal, cwd, claude, codex, plan_only=args.plan_only)


if __name__ == "__main__":
    main()

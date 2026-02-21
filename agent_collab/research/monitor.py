"""Background task monitoring for long-running experiments (e.g., deep learning training)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any

_USE_COLOR = sys.stdout.isatty()


def _c(text: str, *styles: str) -> str:
    if not _USE_COLOR:
        return text
    codes = {
        "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
        "cyan": "\033[96m", "green": "\033[92m", "yellow": "\033[93m",
        "red": "\033[91m", "blue": "\033[94m", "magenta": "\033[95m",
    }
    return "".join(codes.get(s, "") for s in styles) + text + codes["reset"]


SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


@dataclass
class TaskProgress:
    """Represents progress of a long-running task."""
    task_id: str
    started_at: float
    last_update: float
    current_epoch: Optional[int] = None
    total_epochs: Optional[int] = None
    current_metric: Optional[Dict[str, float]] = None
    status: str = "running"  # running | completed | failed
    exit_code: Optional[int] = None
    error_message: str = ""


@dataclass
class CompletionPattern:
    """Pattern to detect task completion in logs."""
    success_patterns: List[str]  # Regex patterns indicating success
    failure_patterns: List[str]  # Regex patterns indicating failure
    completion_file: Optional[str] = None  # File created on completion
    timeout_seconds: Optional[int] = None  # Max time to wait


DEFAULT_PATTERNS = CompletionPattern(
    success_patterns=[
        r"(?i)training\s+completed",
        r"(?i)experiment\s+(?:finished|completed|done)",
        r"(?i)all\s+tasks?\s+complete",
        r"(?i)final\s+results?:",
        r"✓.*complete",
    ],
    failure_patterns=[
        # Python errors
        r"(?i)error:",
        r"(?i)exception:",
        r"(?i)traceback\s*\(most recent call last\)",
        r"(?i)(?:runtime|value|type|attribute|key|index|name)error",
        r"(?i)assertion\s*error",

        # CUDA/GPU errors
        r"CUDA\s+out\s+of\s+memory",
        r"(?i)cuda\s+error",
        r"(?i)gpu\s+out\s+of\s+memory",

        # File/IO errors
        r"(?i)file\s+not\s+found",
        r"(?i)no\s+such\s+file\s+or\s+directory",
        r"(?i)permission\s+denied",

        # Import/Module errors
        r"(?i)modulenotfounderror",
        r"(?i)importerror",
        r"(?i)no\s+module\s+named",

        # General failures
        r"(?i)failed",
        r"(?i)fatal",
        r"(?i)aborted",
        r"(?i)killed",

        # Process exit
        r"(?i)process\s+(?:exited|terminated|killed)",
        r"(?i)exit\s+code\s*:\s*[1-9]",
    ],
    timeout_seconds=24 * 3600,  # 24 hours default
)


class BackgroundMonitor:
    """Monitor a background process and track its progress via log files."""

    def __init__(
        self,
        task_id: str,
        command: str,
        cwd: str = ".",
        log_file: Optional[str] = None,
        patterns: Optional[CompletionPattern] = None,
        progress_callback: Optional[Callable[[TaskProgress], None]] = None,
        poll_interval: int = 5,  # Changed from 30 to 5 for faster updates
        show_log_updates: bool = True,
    ):
        """
        Args:
            task_id: Unique identifier for this task
            command: Shell command to execute
            cwd: Working directory
            log_file: Path to log file to monitor (if None, uses stdout/stderr)
            patterns: Completion detection patterns
            progress_callback: Called periodically with progress updates
            poll_interval: Seconds between log checks
            show_log_updates: If True, periodically show recent log lines
        """
        self.task_id = task_id
        self.command = command
        self.cwd = Path(cwd)
        self.log_file = log_file
        self.patterns = patterns or DEFAULT_PATTERNS
        self.progress_callback = progress_callback
        self.poll_interval = poll_interval
        self.show_log_updates = show_log_updates

        self.process: Optional[subprocess.Popen] = None
        self.progress = TaskProgress(task_id=task_id, started_at=time.time(), last_update=time.time())
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._log_position = 0
        self._last_log_display = 0  # Track when we last showed log tail

    def start(self) -> None:
        """Start the background process and monitoring."""
        # Start process
        log_handle = None
        if self.log_file:
            self.cwd.mkdir(parents=True, exist_ok=True)
            log_path = self.cwd / self.log_file
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(log_path, "w")

        self.process = subprocess.Popen(
            self.command,
            shell=True,
            cwd=str(self.cwd),
            stdout=log_handle or subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        print(_c(f"  🚀 Started background task: {self.task_id}", "cyan"))
        print(_c(f"  📝 PID: {self.process.pid}", "dim"))
        if self.log_file:
            print(_c(f"  📄 Logs: {self.cwd / self.log_file}", "dim"))
        print()

        # Start monitoring thread
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def wait(self, show_spinner: bool = True) -> TaskProgress:
        """Wait for task to complete and return final progress."""
        if show_spinner:
            self._show_live_progress()

        if self._monitor_thread:
            self._monitor_thread.join()

        if self.process:
            self.process.wait()
            self.progress.exit_code = self.process.returncode
            if self.process.returncode != 0 and self.progress.status == "running":
                self.progress.status = "failed"
                self.progress.error_message = f"Process exited with code {self.process.returncode}"

        # Show final log summary and tail
        if self.log_file:
            log_path = self.cwd / self.log_file
            if log_path.exists():
                print_log_summary(log_path, self.task_id)
                print(_c("\n  📝 Final Log Output:", "cyan", "bold"))
                show_log_tail(log_path, lines=15, filter_important=True)

        return self.progress

    def stop(self) -> None:
        """Stop monitoring and terminate the process."""
        self._stop_flag.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def _monitor_loop(self) -> None:
        """Main monitoring loop running in background thread."""
        while not self._stop_flag.is_set():
            if self.process and self.process.poll() is not None:
                # Process finished
                self._check_completion_status()
                break

            # Check timeout
            if self.patterns.timeout_seconds:
                elapsed = time.time() - self.progress.started_at
                if elapsed > self.patterns.timeout_seconds:
                    self.progress.status = "failed"
                    self.progress.error_message = f"Timeout after {elapsed:.0f}s"
                    break

            # Check for stalled process (no log updates for 10 minutes after startup)
            elapsed = time.time() - self.progress.started_at
            time_since_update = time.time() - self.progress.last_update
            if elapsed > 120 and time_since_update > 600:  # After 2min startup, no update for 10min
                self.progress.status = "failed"
                self.progress.error_message = f"Process appears stalled (no log updates for {time_since_update:.0f}s)"
                break

            # Parse logs for progress
            self._parse_log_progress()

            # Check for completion patterns
            if self._check_completion_status():
                break

            # Notify callback
            if self.progress_callback:
                self.progress_callback(self.progress)

            # Periodically show log summary (every 60 seconds)
            if self.show_log_updates and self.log_file:
                current_time = time.time()
                if current_time - self._last_log_display >= 60:
                    self._last_log_display = current_time
                    log_path = self.cwd / self.log_file
                    if log_path.exists():
                        print_log_summary(log_path, self.task_id)

            # Adaptive polling: check more frequently at the start (when errors are most likely)
            elapsed = time.time() - self.progress.started_at
            if elapsed < 60:  # First minute: check every 2 seconds
                poll_time = 2
            elif elapsed < 300:  # First 5 minutes: check every 5 seconds
                poll_time = 5
            else:  # After 5 minutes: use configured interval
                poll_time = self.poll_interval

            time.sleep(poll_time)

    def _parse_log_progress(self) -> None:
        """Parse log file for progress indicators (epoch, metrics, etc.)."""
        if not self.log_file:
            return

        log_path = self.cwd / self.log_file
        if not log_path.exists():
            return

        try:
            with open(log_path, "r") as f:
                f.seek(self._log_position)
                new_lines = f.readlines()
                self._log_position = f.tell()

            for line in new_lines:
                self._parse_line(line.strip())
                self.progress.last_update = time.time()

        except Exception as e:
            # Silently ignore read errors (file might be being written to)
            pass

    def _parse_line(self, line: str) -> None:
        """Parse a single log line for progress info."""
        # Epoch pattern: "Epoch 5/60" or "Epoch: 5/60"
        epoch_match = re.search(r'epoch[:\s]*(\d+)\s*/\s*(\d+)', line, re.IGNORECASE)
        if epoch_match:
            self.progress.current_epoch = int(epoch_match.group(1))
            self.progress.total_epochs = int(epoch_match.group(2))

        # Metric patterns: "Loss: 1.234", "AUC=0.985", "Pixel AP: 58.3%", "I-AUROC=0.9917"
        metric_patterns = [
            (r'loss[:\s]+([\d.]+)', 'loss'),
            (r'auc[:\s=]+([\d.]+)', 'auc'),
            (r'I-AUROC[:\s=]+([\d.]+)', 'I-AUROC'),
            (r'P-AUROC[:\s=]+([\d.]+)', 'P-AUROC'),
            (r'I-AP[:\s=]+([\d.]+)', 'I-AP'),
            (r'P-AP[:\s=]+([\d.]+)', 'P-AP'),
            (r'I-F1[:\s=]+([\d.]+)', 'I-F1'),
            (r'P-F1[:\s=]+([\d.]+)', 'P-F1'),
            (r'AUPRO[:\s=]+([\d.]+)', 'AUPRO'),
            (r'pixel\s*ap[:\s]+([\d.]+)', 'pixel_ap'),
            (r'image\s*auc[:\s]+([\d.]+)', 'image_auc'),
        ]

        if self.progress.current_metric is None:
            self.progress.current_metric = {}

        for pattern, metric_name in metric_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1))
                    # Convert percentage to decimal if needed
                    if value > 1.0 and metric_name != 'loss':
                        value = value / 100.0
                    self.progress.current_metric[metric_name] = value
                except ValueError:
                    pass

    def _check_completion_status(self) -> bool:
        """Check if task has completed (success or failure). Returns True if completed."""
        # Check completion file
        if self.patterns.completion_file:
            file_path = self.cwd / self.patterns.completion_file
            if file_path.exists():
                self.progress.status = "completed"
                return True

        # Check log content for patterns
        if not self.log_file:
            return False

        log_path = self.cwd / self.log_file
        if not log_path.exists():
            return False

        try:
            # Read last 1000 lines (don't read entire huge log)
            with open(log_path, "r") as f:
                lines = f.readlines()[-1000:]
                content = "\n".join(lines)

            # Check failure patterns first
            for pattern in self.patterns.failure_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    self.progress.status = "failed"
                    # Extract detailed error context
                    self.progress.error_message = self._extract_error_details(content, pattern)
                    return True

            # Check success patterns
            for pattern in self.patterns.success_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    self.progress.status = "completed"
                    return True

        except Exception:
            pass

        return False

    def _extract_error_details(self, log_content: str, error_pattern: str) -> str:
        """Extract comprehensive error details from log content."""
        lines = log_content.split('\n')
        error_lines = []

        # Find the error location
        for i, line in enumerate(lines):
            if re.search(error_pattern, line, re.IGNORECASE):
                # Include context: 5 lines before, error line, and up to 20 lines after (for traceback)
                start_idx = max(0, i - 5)
                end_idx = min(len(lines), i + 21)
                error_lines = lines[start_idx:end_idx]
                break

        if not error_lines:
            # Fallback: just return the matched portion
            match = re.search(error_pattern, log_content, re.IGNORECASE)
            if match:
                start = max(0, match.start() - 200)
                end = min(len(log_content), match.end() + 200)
                return log_content[start:end]

        return '\n'.join(error_lines)

    def _show_live_progress(self) -> None:
        """Show live progress with spinner until completion."""
        spinner_idx = 0

        while self.progress.status == "running":
            elapsed = time.time() - self.progress.started_at
            elapsed_str = _format_duration(elapsed)

            # Build status line
            parts = [f"{SPINNER[spinner_idx % len(SPINNER)]}"]

            if self.progress.current_epoch and self.progress.total_epochs:
                progress_pct = (self.progress.current_epoch / self.progress.total_epochs) * 100
                parts.append(f"Epoch {self.progress.current_epoch}/{self.progress.total_epochs} ({progress_pct:.0f}%)")

            if self.progress.current_metric:
                metric_strs = []
                for k, v in self.progress.current_metric.items():
                    if k == 'loss':
                        metric_strs.append(f"Loss={v:.4f}")
                    else:
                        metric_strs.append(f"{k.upper()}={v:.2%}")
                if metric_strs:
                    parts.append(" | ".join(metric_strs))

            parts.append(f"[{elapsed_str}]")

            status_line = "  " + " ".join(parts)
            sys.stderr.write(f"\r{status_line}" + " " * 10)
            sys.stderr.flush()

            time.sleep(0.3)
            spinner_idx += 1

        # Clear spinner line
        sys.stderr.write("\r" + " " * 120 + "\r")
        sys.stderr.flush()

        # Print final status
        elapsed = time.time() - self.progress.started_at
        elapsed_str = _format_duration(elapsed)

        if self.progress.status == "completed":
            print(_c(f"  ✅ Task completed: {self.task_id} ({elapsed_str})", "green", "bold"))
            if self.progress.current_metric:
                for k, v in self.progress.current_metric.items():
                    if k == 'loss':
                        print(_c(f"     • {k}: {v:.4f}", "dim"))
                    else:
                        print(_c(f"     • {k}: {v:.2%}", "dim"))
        elif self.progress.status == "failed":
            print(_c(f"  ❌ Task failed: {self.task_id} ({elapsed_str})", "red", "bold"))
            if self.progress.error_message:
                error_preview = self.progress.error_message[:200]
                print(_c(f"     Error: {error_preview}", "red", "dim"))

        print()


def get_log_content(log_path: Path, max_lines: int = 500) -> str:
    """Get recent log content for error analysis."""
    if not log_path.exists():
        return ""

    try:
        with open(log_path, "r") as f:
            lines = f.readlines()
            # Return last max_lines
            relevant_lines = lines[-max_lines:] if len(lines) > max_lines else lines
            return "".join(relevant_lines)
    except Exception:
        return ""


def _format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.0f}m {seconds%60:.0f}s"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"


def show_log_tail(
    log_path: Path,
    lines: int = 20,
    filter_important: bool = True,
    colorize: bool = True
) -> None:
    """
    Display the last N lines of a log file with optional filtering and coloring.

    Args:
        log_path: Path to log file
        lines: Number of lines to show
        filter_important: If True, only show lines with important info
        colorize: If True, add color coding
    """
    if not log_path.exists():
        print(_c(f"  ⚠️  Log file not found: {log_path}", "yellow"))
        return

    try:
        with open(log_path, "r") as f:
            all_lines = f.readlines()

        # Get last N lines
        tail_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

        if filter_important:
            # Filter for important lines
            important_lines = []
            for line in tail_lines:
                line_lower = line.lower()
                # Keep lines with: epoch, loss, metrics, errors, warnings, completion
                if any(keyword in line_lower for keyword in [
                    'epoch', 'loss', 'auc', 'auroc', 'accuracy', 'error', 'warning',
                    'completed', 'failed', 'metric', 'pixel ap', 'image auc',
                    'i-auroc', 'p-auroc', 'i-ap', 'p-ap', 'i-f1', 'p-f1', 'aupro',
                    'mean', '[baseline]', '[train]'
                ]):
                    important_lines.append(line)

            # If filtering removes everything, show all
            if important_lines:
                tail_lines = important_lines
            else:
                tail_lines = tail_lines[-10:]  # Show last 10 at least

        print(_c(f"\n  📄 Recent Log (last {len(tail_lines)} lines):", "cyan", "bold"))
        print(_c("  " + "─" * 60, "dim"))

        for line in tail_lines:
            line = line.strip()
            if not line:
                continue

            # Colorize based on content
            if colorize:
                line_lower = line.lower()
                if 'error' in line_lower or 'exception' in line_lower or 'failed' in line_lower:
                    print(_c(f"  {line}", "red"))
                elif 'warning' in line_lower:
                    print(_c(f"  {line}", "yellow"))
                elif 'completed' in line_lower or 'success' in line_lower:
                    print(_c(f"  {line}", "green"))
                elif 'epoch' in line_lower:
                    print(_c(f"  {line}", "cyan"))
                else:
                    print(f"  {line}")
            else:
                print(f"  {line}")

        print(_c("  " + "─" * 60, "dim"))

    except Exception as e:
        print(_c(f"  ⚠️  Error reading log: {e}", "yellow"))


def get_log_summary(log_path: Path) -> Dict[str, Any]:
    """
    Extract a summary of key information from the log file.

    Returns dict with: current_epoch, total_epochs, latest_metrics, errors, status
    """
    summary = {
        "current_epoch": None,
        "total_epochs": None,
        "latest_metrics": {},
        "errors": [],
        "warnings": [],
        "status": "running"
    }

    if not log_path.exists():
        return summary

    try:
        with open(log_path, "r") as f:
            lines = f.readlines()

        # Analyze last 100 lines for recent status
        recent_lines = lines[-100:] if len(lines) > 100 else lines

        for line in recent_lines:
            line = line.strip()

            # Parse epoch
            epoch_match = re.search(r'epoch[:\s]*(\d+)\s*/\s*(\d+)', line, re.IGNORECASE)
            if epoch_match:
                summary["current_epoch"] = int(epoch_match.group(1))
                summary["total_epochs"] = int(epoch_match.group(2))

            # Parse metrics
            metric_patterns = [
                (r'loss[:\s]+([\d.]+)', 'loss'),
                (r'auc[:\s=]+([\d.]+)', 'auc'),
                (r'I-AUROC[:\s=]+([\d.]+)', 'I-AUROC'),
                (r'P-AUROC[:\s=]+([\d.]+)', 'P-AUROC'),
                (r'I-AP[:\s=]+([\d.]+)', 'I-AP'),
                (r'P-AP[:\s=]+([\d.]+)', 'P-AP'),
                (r'I-F1[:\s=]+([\d.]+)', 'I-F1'),
                (r'P-F1[:\s=]+([\d.]+)', 'P-F1'),
                (r'AUPRO[:\s=]+([\d.]+)', 'AUPRO'),
                (r'pixel\s*ap[:\s]+([\d.]+)', 'pixel_ap'),
                (r'image\s*auc[:\s]+([\d.]+)', 'image_auc'),
                (r'accuracy[:\s]+([\d.]+)', 'accuracy'),
            ]

            for pattern, metric_name in metric_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    try:
                        value = float(match.group(1))
                        if value > 1.0 and metric_name != 'loss':
                            value = value / 100.0
                        summary["latest_metrics"][metric_name] = value
                    except ValueError:
                        pass

            # Detect errors
            if re.search(r'error:|exception:', line, re.IGNORECASE):
                if len(summary["errors"]) < 3:  # Keep last 3 errors
                    summary["errors"].append(line[:150])

            # Detect warnings
            if 'warning' in line.lower():
                if len(summary["warnings"]) < 3:
                    summary["warnings"].append(line[:150])

            # Check completion
            if re.search(r'(?i)training\s+completed|experiment\s+(?:finished|completed)', line):
                summary["status"] = "completed"
            elif re.search(r'(?i)failed|error:', line):
                summary["status"] = "failed"

        return summary

    except Exception as e:
        summary["errors"] = [f"Failed to read log: {e}"]
        return summary


def print_log_summary(log_path: Path, task_id: str = "Task") -> None:
    """Print a concise summary of the log file."""
    summary = get_log_summary(log_path)

    # Don't print if there's no meaningful information
    has_info = (
        summary["current_epoch"] or
        summary["latest_metrics"] or
        summary["errors"] or
        summary["warnings"]
    )

    if not has_info:
        # Print minimal message
        print(_c(f"  📊 {task_id} - No metrics found yet (log may be initializing)", "dim"))
        return

    print()
    print(_c("  " + "─" * 70, "cyan"))
    print(_c(f"  📊 {task_id} - Live Update", "cyan", "bold"))
    print(_c("  " + "─" * 70, "cyan"))

    # Status
    status_color = "green" if summary["status"] == "completed" else "yellow" if summary["status"] == "running" else "red"
    status_icon = "✅" if summary["status"] == "completed" else "🔄" if summary["status"] == "running" else "❌"
    print(_c(f"  {status_icon} Status: {summary['status'].upper()}", status_color, "bold"))

    # Progress
    if summary["current_epoch"] and summary["total_epochs"]:
        progress = (summary["current_epoch"] / summary["total_epochs"]) * 100
        bar_width = 30
        filled = int(bar_width * progress / 100)
        bar = "█" * filled + "░" * (bar_width - filled)
        print(_c(f"  📈 Progress: Epoch {summary['current_epoch']}/{summary['total_epochs']}", "cyan", "bold"))
        print(_c(f"     {bar} {progress:.1f}%", "cyan"))

    # Metrics
    if summary["latest_metrics"]:
        print(_c(f"  📊 Latest Metrics:", "bold"))
        for metric, value in summary["latest_metrics"].items():
            if metric == 'loss':
                print(_c(f"     • {metric.upper()}: {value:.4f}", "yellow"))
            else:
                print(_c(f"     • {metric.upper()}: {value:.2%}", "green"))

    # Errors
    if summary["errors"]:
        print(_c(f"  ⚠️  Errors ({len(summary['errors'])}):", "red", "bold"))
        for err in summary["errors"][:3]:  # Show max 3 errors
            print(_c(f"     • {err[:80]}", "red"))
        if len(summary["errors"]) > 3:
            print(_c(f"     ... and {len(summary['errors']) - 3} more", "red", "dim"))

    # Warnings
    if summary["warnings"]:
        print(_c(f"  ⚠️  Warnings ({len(summary['warnings'])}):", "yellow"))
        for warn in summary["warnings"][:3]:  # Show max 3 warnings
            print(_c(f"     • {warn[:80]}", "yellow", "dim"))
        if len(summary["warnings"]) > 3:
            print(_c(f"     ... and {len(summary['warnings']) - 3} more", "yellow", "dim"))

    print(_c("  " + "─" * 70, "dim"))
    print()


def run_background_task(
    task_id: str,
    command: str,
    cwd: str = ".",
    log_file: Optional[str] = None,
    patterns: Optional[CompletionPattern] = None,
    wait: bool = True,
    show_log_updates: bool = True,
) -> TaskProgress:
    """
    Run a command in the background and monitor its progress.

    Args:
        task_id: Unique identifier for logging
        command: Shell command to execute
        cwd: Working directory
        log_file: Log file path relative to cwd
        patterns: Completion detection patterns
        wait: If True, block until completion; if False, return immediately
        show_log_updates: If True, show periodic log summaries

    Returns:
        TaskProgress with final status
    """
    monitor = BackgroundMonitor(
        task_id=task_id,
        command=command,
        cwd=cwd,
        log_file=log_file,
        patterns=patterns,
        show_log_updates=show_log_updates,
    )

    monitor.start()

    if wait:
        return monitor.wait()
    else:
        # Return progress object that can be queried later
        return monitor.progress


# ─── Integration with research steps ─────────────────────────────────────────

def parse_experiment_command(agent_output: str) -> Optional[Dict[str, Any]]:
    """
    Parse agent output to extract background command details.

    Expected format in agent output:
    ```
    BACKGROUND_TASK: true
    COMMAND: python run_moleflow.py --task_classes leather grid --num_epochs 60
    LOG_FILE: logs/V65_exp1/training.log
    COMPLETION_PATTERN: Training completed
    ESTIMATED_TIME: 4-6 hours
    ```

    Returns dict with: command, log_file, completion_patterns, estimated_time
    """
    if "BACKGROUND_TASK:" not in agent_output.upper():
        return None

    info: Dict[str, Any] = {}

    # Extract command
    cmd_match = re.search(r'COMMAND:\s*(.+?)(?:\n|$)', agent_output, re.IGNORECASE)
    if cmd_match:
        info['command'] = cmd_match.group(1).strip()
    else:
        return None  # Command is required

    # Extract log file
    log_match = re.search(r'LOG_FILE:\s*(.+?)(?:\n|$)', agent_output, re.IGNORECASE)
    if log_match:
        info['log_file'] = log_match.group(1).strip()

    # Extract completion pattern
    pattern_match = re.search(r'COMPLETION_PATTERN:\s*(.+?)(?:\n|$)', agent_output, re.IGNORECASE)
    if pattern_match:
        custom_patterns = CompletionPattern(
            success_patterns=[pattern_match.group(1).strip(), *DEFAULT_PATTERNS.success_patterns],
            failure_patterns=DEFAULT_PATTERNS.failure_patterns,
        )
        info['patterns'] = custom_patterns

    # Extract estimated time
    time_match = re.search(r'ESTIMATED_TIME:\s*(.+?)(?:\n|$)', agent_output, re.IGNORECASE)
    if time_match:
        info['estimated_time'] = time_match.group(1).strip()

    return info

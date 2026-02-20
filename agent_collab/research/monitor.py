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
        r"(?i)error:",
        r"(?i)exception:",
        r"(?i)failed",
        r"(?i)traceback",
        r"CUDA\s+out\s+of\s+memory",
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
        poll_interval: int = 30,
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
        """
        self.task_id = task_id
        self.command = command
        self.cwd = Path(cwd)
        self.log_file = log_file
        self.patterns = patterns or DEFAULT_PATTERNS
        self.progress_callback = progress_callback
        self.poll_interval = poll_interval

        self.process: Optional[subprocess.Popen] = None
        self.progress = TaskProgress(task_id=task_id, started_at=time.time(), last_update=time.time())
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._log_position = 0

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

            # Parse logs for progress
            self._parse_log_progress()

            # Check for completion patterns
            if self._check_completion_status():
                break

            # Notify callback
            if self.progress_callback:
                self.progress_callback(self.progress)

            time.sleep(self.poll_interval)

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

        # Metric patterns: "Loss: 1.234", "AUC=0.985", "Pixel AP: 58.3%"
        metric_patterns = [
            (r'loss[:\s]+([\d.]+)', 'loss'),
            (r'auc[:\s=]+([\d.]+)', 'auc'),
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
                    # Extract error context
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        start = max(0, match.start() - 100)
                        end = min(len(content), match.end() + 100)
                        self.progress.error_message = content[start:end]
                    return True

            # Check success patterns
            for pattern in self.patterns.success_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    self.progress.status = "completed"
                    return True

        except Exception:
            pass

        return False

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


def run_background_task(
    task_id: str,
    command: str,
    cwd: str = ".",
    log_file: Optional[str] = None,
    patterns: Optional[CompletionPattern] = None,
    wait: bool = True,
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

    Returns:
        TaskProgress with final status
    """
    monitor = BackgroundMonitor(
        task_id=task_id,
        command=command,
        cwd=cwd,
        log_file=log_file,
        patterns=patterns,
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

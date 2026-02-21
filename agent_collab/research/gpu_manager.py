"""GPU management for parallel experiment execution."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class GPUInfo:
    """Information about a GPU device."""
    index: int
    name: str
    memory_total: int  # MB
    memory_used: int   # MB
    memory_free: int   # MB
    utilization: int   # %

    @property
    def memory_free_gb(self) -> float:
        return self.memory_free / 1024.0

    def __str__(self) -> str:
        return f"GPU {self.index}: {self.name} ({self.memory_free_gb:.1f}GB free)"


def detect_gpus() -> list[GPUInfo]:
    """Detect available GPUs using nvidia-smi."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu",
                "--format=csv,noheader,nounits"
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return []

        gpus = []
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 6:
                gpus.append(GPUInfo(
                    index=int(parts[0]),
                    name=parts[1],
                    memory_total=int(parts[2]),
                    memory_used=int(parts[3]),
                    memory_free=int(parts[4]),
                    utilization=int(parts[5])
                ))

        return gpus

    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return []


def select_available_gpus(
    required_memory_gb: Optional[float] = None,
    max_utilization: int = 30
) -> list[int]:
    """
    Select available GPUs based on memory and utilization.

    Args:
        required_memory_gb: Minimum free memory required (GB)
        max_utilization: Maximum utilization threshold (%)

    Returns:
        List of GPU indices that meet the criteria
    """
    gpus = detect_gpus()
    if not gpus:
        return []

    available = []
    for gpu in gpus:
        # Check memory requirement
        if required_memory_gb and gpu.memory_free_gb < required_memory_gb:
            continue

        # Check utilization
        if gpu.utilization > max_utilization:
            continue

        available.append(gpu.index)

    return available


def allocate_gpus_to_experiments(
    n_experiments: int,
    required_memory_gb: Optional[float] = None
) -> dict[int, list[int]]:
    """
    Allocate GPUs to experiments for parallel execution.

    Args:
        n_experiments: Number of experiments to run
        required_memory_gb: Memory requirement per experiment

    Returns:
        Dict mapping experiment index to list of GPU indices
        Example: {0: [0], 1: [1], 2: [0, 1]} for 3 experiments on 2 GPUs
    """
    available_gpus = select_available_gpus(required_memory_gb)

    if not available_gpus:
        # No GPUs available or detected, return empty allocation
        # Experiments will run on CPU or default GPU
        return {i: [] for i in range(n_experiments)}

    allocation = {}

    if len(available_gpus) >= n_experiments:
        # One GPU per experiment (best case)
        for i in range(n_experiments):
            allocation[i] = [available_gpus[i]]
    else:
        # Distribute experiments across available GPUs
        for i in range(n_experiments):
            gpu_idx = available_gpus[i % len(available_gpus)]
            allocation[i] = [gpu_idx]

    return allocation


def format_cuda_visible_devices(gpu_indices: list[int]) -> str:
    """Format GPU indices for CUDA_VISIBLE_DEVICES environment variable."""
    if not gpu_indices:
        return ""
    return ",".join(str(i) for i in gpu_indices)


def print_gpu_status(use_color: bool = True) -> None:
    """Print current GPU status."""
    def _c(text: str, *styles: str) -> str:
        if not use_color or not sys.stdout.isatty():
            return text
        codes = {
            "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
            "cyan": "\033[96m", "green": "\033[92m", "yellow": "\033[93m",
            "red": "\033[91m",
        }
        return "".join(codes.get(s, "") for s in styles) + text + codes["reset"]

    gpus = detect_gpus()

    if not gpus:
        print(_c("  ℹ️  No GPUs detected (will use CPU)", "dim"))
        return

    print()
    print(_c("  🖥️  Available GPUs:", "cyan", "bold"))
    for gpu in gpus:
        util_color = "green" if gpu.utilization < 30 else "yellow" if gpu.utilization < 70 else "red"
        mem_color = "green" if gpu.memory_free_gb > 8 else "yellow" if gpu.memory_free_gb > 4 else "red"

        print(
            f"    GPU {gpu.index}: {gpu.name:25} | "
            + _c(f"{gpu.memory_free_gb:5.1f}GB free", mem_color)
            + f" | "
            + _c(f"{gpu.utilization:3d}% util", util_color)
        )
    print()

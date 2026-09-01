"""
evals – Evaluations- & Benchmark-Framework für das KI-Softwareentwickler-Team
"""

from evals.runner import (
    BenchmarkSuiteResult,
    BenchmarkTaskResult,
    run_benchmark,
    run_single_task,
)
from evals.tasks import BENCHMARK_TASKS, BenchmarkTask, get_task, list_tasks

__all__ = [
    "BENCHMARK_TASKS",
    "BenchmarkSuiteResult",
    "BenchmarkTask",
    "BenchmarkTaskResult",
    "get_task",
    "list_tasks",
    "run_benchmark",
    "run_single_task",
]

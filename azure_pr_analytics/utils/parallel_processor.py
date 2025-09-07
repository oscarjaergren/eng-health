"""Enhanced parallel processing utilities for improved performance."""

import logging
import multiprocessing as mp
import threading
import time
from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


@dataclass
class ProcessingTask:
    """Represents a processing task with metadata."""

    id: str
    func: Callable
    args: Tuple
    kwargs: Dict
    priority: int = 0
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class ProcessingResult:
    """Represents the result of a processing task."""

    task_id: str
    success: bool
    result: Any = None
    error: Optional[Exception] = None
    execution_time: float = 0.0
    retry_count: int = 0


class AdaptiveParallelProcessor:
    """
    Enhanced parallel processor with adaptive concurrency and intelligent task distribution.

    Features:
    - Adaptive concurrency based on system load
    - Priority-based task scheduling
    - Automatic retry with exponential backoff
    - Memory-efficient batch processing
    - Progress tracking and monitoring
    - Mixed thread/process pool execution
    """

    def __init__(
        self,
        max_workers: Optional[int] = None,
        use_processes: bool = False,
        adaptive_scaling: bool = True,
        batch_size: int = 100,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the adaptive parallel processor.

        Args:
            max_workers: Maximum number of workers (auto-detected if None)
            use_processes: Use process pool instead of thread pool
            adaptive_scaling: Enable adaptive worker scaling
            batch_size: Batch size for memory-efficient processing
            logger: Logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
        self.use_processes = use_processes
        self.adaptive_scaling = adaptive_scaling
        self.batch_size = batch_size

        # Determine optimal worker count
        cpu_count = mp.cpu_count()
        if max_workers is None:
            if use_processes:
                self.max_workers = cpu_count
            else:
                # For I/O bound tasks (API calls), use more threads
                self.max_workers = min(cpu_count * 4, 32)
        else:
            self.max_workers = max_workers

        self.current_workers = self.max_workers
        self.task_queue: Queue = Queue()
        self.results: List[ProcessingResult] = []
        self.active_tasks: Dict[str, ProcessingTask] = {}

        # Performance metrics
        self.total_tasks = 0
        self.completed_tasks = 0
        self.failed_tasks = 0
        self.start_time = 0.0

        # Thread safety
        self.lock = threading.Lock()

    def _create_executor(
        self, num_workers: int
    ) -> Union[ThreadPoolExecutor, ProcessPoolExecutor]:
        """Create appropriate executor based on configuration."""
        if self.use_processes:
            return ProcessPoolExecutor(max_workers=num_workers)
        else:
            return ThreadPoolExecutor(max_workers=num_workers)

    def _calculate_optimal_workers(self, task_count: int, avg_task_time: float) -> int:
        """Calculate optimal number of workers based on task characteristics."""
        if not self.adaptive_scaling:
            return self.max_workers

        # Adaptive scaling based on task count and estimated execution time
        if task_count < 10:
            return min(task_count, 4)
        elif avg_task_time > 5.0:  # Long-running tasks
            return min(self.max_workers // 2, task_count)
        else:  # Short tasks
            return min(self.max_workers, task_count)

    def _execute_task(self, task: ProcessingTask) -> ProcessingResult:
        """Execute a single task with error handling and timing."""
        start_time = time.time()

        try:
            result = task.func(*task.args, **task.kwargs)
            execution_time = time.time() - start_time

            return ProcessingResult(
                task_id=task.id,
                success=True,
                result=result,
                execution_time=execution_time,
                retry_count=task.retry_count,
            )

        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.warning(
                f"Task {task.id} failed (attempt {task.retry_count + 1}): {e}"
            )

            return ProcessingResult(
                task_id=task.id,
                success=False,
                error=e,
                execution_time=execution_time,
                retry_count=task.retry_count,
            )

    def _should_retry(self, task: ProcessingTask, result: ProcessingResult) -> bool:
        """Determine if a failed task should be retried."""
        if result.success:
            return False

        if task.retry_count >= task.max_retries:
            return False

        # Don't retry certain types of errors
        if isinstance(result.error, (ValueError, TypeError, KeyError)):
            return False

        return True

    def add_task(
        self,
        task_id: str,
        func: Callable,
        args: Tuple = (),
        kwargs: Dict = None,
        priority: int = 0,
        max_retries: int = 3,
    ) -> None:
        """
        Add a task to the processing queue.

        Args:
            task_id: Unique identifier for the task
            func: Function to execute
            args: Function arguments
            kwargs: Function keyword arguments
            priority: Task priority (higher = more important)
            max_retries: Maximum retry attempts
        """
        task = ProcessingTask(
            id=task_id,
            func=func,
            args=args,
            kwargs=kwargs or {},
            priority=priority,
            max_retries=max_retries,
        )

        with self.lock:
            self.task_queue.put(task)
            self.total_tasks += 1

    def add_batch_tasks(self, tasks: List[Dict[str, Any]]) -> None:
        """
        Add multiple tasks in batch for better performance.

        Args:
            tasks: List of task dictionaries with keys: id, func, args, kwargs, priority, max_retries
        """
        with self.lock:
            for task_data in tasks:
                task = ProcessingTask(
                    id=task_data["id"],
                    func=task_data["func"],
                    args=task_data.get("args", ()),
                    kwargs=task_data.get("kwargs", {}),
                    priority=task_data.get("priority", 0),
                    max_retries=task_data.get("max_retries", 3),
                )
                self.task_queue.put(task)
                self.total_tasks += 1

    def process_all(
        self, progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[ProcessingResult]:
        """
        Process all queued tasks with enhanced parallel execution.

        Args:
            progress_callback: Optional callback for progress updates (completed, total)

        Returns:
            List of processing results
        """
        if self.task_queue.empty():
            self.logger.warning("No tasks to process")
            return []

        self.start_time = time.time()
        self.results.clear()

        # Convert queue to list for better handling
        tasks = []
        while not self.task_queue.empty():
            try:
                tasks.append(self.task_queue.get_nowait())
            except Empty:
                break

        # Sort tasks by priority (higher priority first)
        tasks.sort(key=lambda t: t.priority, reverse=True)

        # Calculate optimal worker count
        avg_task_time = 1.0  # Initial estimate
        optimal_workers = self._calculate_optimal_workers(len(tasks), avg_task_time)

        self.logger.info(
            f"Processing {len(tasks)} tasks with {optimal_workers} workers"
        )

        # Process tasks in batches for memory efficiency
        for batch_start in range(0, len(tasks), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(tasks))
            batch_tasks = tasks[batch_start:batch_end]

            self._process_batch(batch_tasks, optimal_workers, progress_callback)

            # Update average task time for adaptive scaling
            if self.results:
                avg_task_time = sum(
                    r.execution_time for r in self.results[-len(batch_tasks) :]
                ) / len(batch_tasks)
                optimal_workers = self._calculate_optimal_workers(
                    len(tasks) - batch_end, avg_task_time
                )

        # Process any retry tasks
        self._process_retries(optimal_workers, progress_callback)

        total_time = time.time() - self.start_time
        success_rate = (
            (self.completed_tasks / self.total_tasks) * 100
            if self.total_tasks > 0
            else 0
        )

        self.logger.info(
            f"Processing completed: {self.completed_tasks}/{self.total_tasks} tasks "
            f"({success_rate:.1f}% success rate) in {total_time:.2f}s"
        )

        return self.results.copy()

    def _process_batch(
        self,
        batch_tasks: List[ProcessingTask],
        num_workers: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """Process a batch of tasks with the specified number of workers."""
        with self._create_executor(num_workers) as executor:
            # Submit all tasks
            future_to_task = {
                executor.submit(self._execute_task, task): task for task in batch_tasks
            }

            # Process completed tasks
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                result = future.result()

                with self.lock:
                    self.results.append(result)

                    if result.success:
                        self.completed_tasks += 1
                    else:
                        # Check if task should be retried
                        if self._should_retry(task, result):
                            task.retry_count += 1
                            # Add exponential backoff delay
                            time.sleep(min(2**task.retry_count, 30))
                            self.task_queue.put(task)
                        else:
                            self.failed_tasks += 1

                    # Progress callback
                    if progress_callback:
                        progress_callback(
                            self.completed_tasks + self.failed_tasks, self.total_tasks
                        )

    def _process_retries(
        self,
        num_workers: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """Process any retry tasks."""
        retry_tasks = []
        while not self.task_queue.empty():
            try:
                retry_tasks.append(self.task_queue.get_nowait())
            except Empty:
                break

        if retry_tasks:
            self.logger.info(f"Processing {len(retry_tasks)} retry tasks")
            self._process_batch(retry_tasks, num_workers, progress_callback)

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get processing statistics.

        Returns:
            Dictionary containing processing statistics
        """
        total_time = time.time() - self.start_time if self.start_time > 0 else 0

        successful_results = [r for r in self.results if r.success]
        [r for r in self.results if not r.success]

        stats = {
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "success_rate": (
                (self.completed_tasks / self.total_tasks) * 100
                if self.total_tasks > 0
                else 0
            ),
            "total_execution_time": total_time,
            "average_task_time": (
                sum(r.execution_time for r in successful_results)
                / len(successful_results)
                if successful_results
                else 0
            ),
            "max_task_time": max(
                (r.execution_time for r in successful_results), default=0
            ),
            "min_task_time": min(
                (r.execution_time for r in successful_results), default=0
            ),
            "retry_count": sum(r.retry_count for r in self.results),
            "worker_count": self.current_workers,
            "tasks_per_second": (
                self.completed_tasks / total_time if total_time > 0 else 0
            ),
        }

        return stats

    def clear(self) -> None:
        """Clear all tasks and results."""
        with self.lock:
            # Clear queue
            while not self.task_queue.empty():
                try:
                    self.task_queue.get_nowait()
                except Empty:
                    break

            self.results.clear()
            self.active_tasks.clear()
            self.total_tasks = 0
            self.completed_tasks = 0
            self.failed_tasks = 0
            self.start_time = 0.0


class BatchProcessor:
    """Utility class for processing large datasets in memory-efficient batches."""

    @staticmethod
    def process_in_batches(
        data: List[Any],
        process_func: Callable[[List[Any]], List[Any]],
        batch_size: int = 1000,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[Any]:
        """
        Process large datasets in batches to manage memory usage.

        Args:
            data: List of data items to process
            process_func: Function that processes a batch and returns results
            batch_size: Size of each batch
            progress_callback: Optional progress callback

        Returns:
            Combined results from all batches
        """
        results = []
        total_items = len(data)
        processed_items = 0

        for i in range(0, total_items, batch_size):
            batch = data[i : i + batch_size]
            batch_results = process_func(batch)
            results.extend(batch_results)

            processed_items += len(batch)
            if progress_callback:
                progress_callback(processed_items, total_items)

        return results

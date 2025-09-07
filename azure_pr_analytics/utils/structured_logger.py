"""Structured logging system with context and correlation IDs for better monitoring."""

import json
import logging
import logging.handlers
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import local
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass, asdict
import traceback


@dataclass
class LogContext:
    """Represents logging context with correlation and operation details."""

    correlation_id: str
    operation: str
    component: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {k: v for k, v in asdict(self).items() if v is not None}


class ContextualLogger:
    """
    Enhanced logger with structured logging, context management, and correlation IDs.

    Features:
    - Structured JSON logging
    - Correlation ID tracking across operations
    - Context-aware logging with metadata
    - Performance metrics integration
    - Configurable log levels and outputs
    - Thread-safe context management
    """

    def __init__(
        self,
        name: str,
        log_level: str = "INFO",
        log_file: Optional[str] = None,
        enable_console: bool = True,
        enable_json: bool = True,
        max_file_size: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
    ):
        """
        Initialize the contextual logger.

        Args:
            name: Logger name
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_file: Path to log file (optional)
            enable_console: Enable console logging
            enable_json: Enable JSON structured logging
            max_file_size: Maximum log file size before rotation
            backup_count: Number of backup files to keep
        """
        self.name = name
        self.enable_json = enable_json
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, log_level.upper()))

        # Thread-local storage for context
        self._local = local()

        # Clear existing handlers
        self.logger.handlers.clear()

        # Setup formatters
        if enable_json:
            formatter = StructuredFormatter()
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )

        # Console handler
        if enable_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

        # File handler with rotation
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=max_file_size, backupCount=backup_count
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def _get_context(self) -> Optional[LogContext]:
        """Get current logging context from thread-local storage."""
        return getattr(self._local, "context", None)

    def _set_context(self, context: Optional[LogContext]) -> None:
        """Set logging context in thread-local storage."""
        self._local.context = context

    @contextmanager
    def context(
        self,
        operation: str,
        component: str,
        correlation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        **metadata,
    ):
        """
        Context manager for structured logging with correlation IDs.

        Args:
            operation: Name of the operation being performed
            component: Component/module performing the operation
            correlation_id: Correlation ID (auto-generated if None)
            user_id: User identifier
            session_id: Session identifier
            request_id: Request identifier
            **metadata: Additional metadata
        """
        # Generate correlation ID if not provided
        if correlation_id is None:
            correlation_id = str(uuid.uuid4())[:8]

        # Create context
        context = LogContext(
            correlation_id=correlation_id,
            operation=operation,
            component=component,
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
            metadata=metadata if metadata else None,
        )

        # Store previous context
        previous_context = self._get_context()

        try:
            # Set new context
            self._set_context(context)

            # Log operation start
            self.info(
                f"Operation started: {operation}",
                extra={
                    "event_type": "operation_start",
                    "operation": operation,
                    "component": component,
                },
            )

            start_time = time.time()
            yield context

            # Log operation completion
            duration = time.time() - start_time
            self.info(
                f"Operation completed: {operation}",
                extra={
                    "event_type": "operation_complete",
                    "operation": operation,
                    "component": component,
                    "duration_seconds": round(duration, 3),
                },
            )

        except Exception as e:
            # Log operation failure
            duration = time.time() - start_time
            self.error(
                f"Operation failed: {operation}",
                extra={
                    "event_type": "operation_failed",
                    "operation": operation,
                    "component": component,
                    "duration_seconds": round(duration, 3),
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "traceback": traceback.format_exc(),
                },
            )
            raise

        finally:
            # Restore previous context
            self._set_context(previous_context)

    def _log_with_context(
        self, level: int, message: str, extra: Optional[Dict] = None
    ) -> None:
        """Log message with current context information."""
        # Get current context
        context = self._get_context()

        # Prepare extra data
        log_extra = extra or {}

        if context:
            log_extra.update(context.to_dict())

        # Add timestamp
        log_extra["timestamp"] = datetime.utcnow().isoformat()

        # Log the message
        self.logger.log(level, message, extra=log_extra)

    def debug(self, message: str, extra: Optional[Dict] = None) -> None:
        """Log debug message with context."""
        self._log_with_context(logging.DEBUG, message, extra)

    def info(self, message: str, extra: Optional[Dict] = None) -> None:
        """Log info message with context."""
        self._log_with_context(logging.INFO, message, extra)

    def warning(self, message: str, extra: Optional[Dict] = None) -> None:
        """Log warning message with context."""
        self._log_with_context(logging.WARNING, message, extra)

    def error(self, message: str, extra: Optional[Dict] = None) -> None:
        """Log error message with context."""
        self._log_with_context(logging.ERROR, message, extra)

    def critical(self, message: str, extra: Optional[Dict] = None) -> None:
        """Log critical message with context."""
        self._log_with_context(logging.CRITICAL, message, extra)

    def log_performance_metric(
        self,
        metric_name: str,
        value: Union[int, float],
        unit: str = "count",
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Log performance metric with structured format.

        Args:
            metric_name: Name of the metric
            value: Metric value
            unit: Unit of measurement
            tags: Additional tags for the metric
        """
        self.info(
            f"Performance metric: {metric_name}",
            extra={
                "event_type": "performance_metric",
                "metric_name": metric_name,
                "metric_value": value,
                "metric_unit": unit,
                "metric_tags": tags or {},
            },
        )

    def log_api_call(
        self,
        url: str,
        method: str = "GET",
        status_code: Optional[int] = None,
        duration: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Log API call with structured format.

        Args:
            url: API endpoint URL
            method: HTTP method
            status_code: Response status code
            duration: Request duration in seconds
            error: Error message if request failed
        """
        extra_data = {"event_type": "api_call", "api_url": url, "api_method": method}

        if status_code is not None:
            extra_data["api_status_code"] = status_code

        if duration is not None:
            extra_data["api_duration_seconds"] = round(duration, 3)

        if error:
            extra_data["api_error"] = error
            self.error(f"API call failed: {method} {url}", extra=extra_data)
        else:
            self.info(f"API call: {method} {url}", extra=extra_data)

    def log_data_processing(
        self,
        operation: str,
        input_count: int,
        output_count: int,
        duration: float,
        errors: int = 0,
    ) -> None:
        """
        Log data processing operation with metrics.

        Args:
            operation: Processing operation name
            input_count: Number of input items
            output_count: Number of output items
            duration: Processing duration in seconds
            errors: Number of errors encountered
        """
        self.info(
            f"Data processing: {operation}",
            extra={
                "event_type": "data_processing",
                "processing_operation": operation,
                "input_count": input_count,
                "output_count": output_count,
                "processing_duration_seconds": round(duration, 3),
                "error_count": errors,
                "success_rate": (
                    ((input_count - errors) / input_count * 100)
                    if input_count > 0
                    else 0
                ),
            },
        )


class StructuredFormatter(logging.Formatter):
    """Custom formatter for structured JSON logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as structured JSON."""
        # Base log data
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields from the record
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "getMessage",
                "exc_info",
                "exc_text",
                "stack_info",
            ]:
                log_data[key] = value

        return json.dumps(log_data, default=str, ensure_ascii=False)


class ProgressTracker:
    """
    Progress tracking utility with structured logging integration.

    Features:
    - Progress percentage tracking
    - ETA calculation
    - Throughput metrics
    - Structured logging of progress events
    """

    def __init__(
        self,
        total_items: int,
        operation_name: str,
        logger: ContextualLogger,
        log_interval: int = 100,
    ):
        """
        Initialize progress tracker.

        Args:
            total_items: Total number of items to process
            operation_name: Name of the operation
            logger: Contextual logger instance
            log_interval: Log progress every N items
        """
        self.total_items = total_items
        self.operation_name = operation_name
        self.logger = logger
        self.log_interval = log_interval

        self.processed_items = 0
        self.start_time = time.time()
        self.last_log_time = self.start_time
        self.last_log_count = 0

    def update(self, increment: int = 1) -> None:
        """
        Update progress by specified increment.

        Args:
            increment: Number of items processed
        """
        self.processed_items += increment

        # Log progress at intervals
        if (
            self.processed_items % self.log_interval == 0
            or self.processed_items == self.total_items
        ):
            self._log_progress()

    def _log_progress(self) -> None:
        """Log current progress with metrics."""
        current_time = time.time()
        elapsed_time = current_time - self.start_time

        # Calculate progress percentage
        progress_pct = (self.processed_items / self.total_items) * 100

        # Calculate ETA
        if self.processed_items > 0:
            rate = self.processed_items / elapsed_time
            remaining_items = self.total_items - self.processed_items
            eta_seconds = remaining_items / rate if rate > 0 else 0
        else:
            eta_seconds = 0

        # Calculate current throughput
        time_since_last_log = current_time - self.last_log_time
        items_since_last_log = self.processed_items - self.last_log_count
        current_throughput = (
            items_since_last_log / time_since_last_log if time_since_last_log > 0 else 0
        )

        # Log progress
        self.logger.info(
            f"Progress: {self.operation_name}",
            extra={
                "event_type": "progress_update",
                "operation": self.operation_name,
                "processed_items": self.processed_items,
                "total_items": self.total_items,
                "progress_percentage": round(progress_pct, 1),
                "elapsed_seconds": round(elapsed_time, 1),
                "eta_seconds": round(eta_seconds, 1),
                "throughput_items_per_second": round(current_throughput, 2),
                "average_throughput_items_per_second": (
                    round(self.processed_items / elapsed_time, 2)
                    if elapsed_time > 0
                    else 0
                ),
            },
        )

        # Update tracking variables
        self.last_log_time = current_time
        self.last_log_count = self.processed_items

    def complete(self) -> None:
        """Mark operation as complete and log final metrics."""
        total_time = time.time() - self.start_time
        average_throughput = self.processed_items / total_time if total_time > 0 else 0

        self.logger.info(
            f"Progress complete: {self.operation_name}",
            extra={
                "event_type": "progress_complete",
                "operation": self.operation_name,
                "total_items": self.total_items,
                "processed_items": self.processed_items,
                "total_duration_seconds": round(total_time, 2),
                "average_throughput_items_per_second": round(average_throughput, 2),
            },
        )


# Global logger factory
def create_logger(name: str, **kwargs) -> ContextualLogger:
    """
    Factory function to create contextual loggers with consistent configuration.

    Args:
        name: Logger name
        **kwargs: Additional configuration options

    Returns:
        Configured ContextualLogger instance
    """
    # Default configuration
    default_config = {
        "log_level": "INFO",
        "log_file": f"logs/{name}.log",
        "enable_console": True,
        "enable_json": True,
    }

    # Merge with provided kwargs
    config = {**default_config, **kwargs}

    return ContextualLogger(name, **config)

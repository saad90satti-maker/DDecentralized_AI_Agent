"""
Retry decorator with exponential backoff, circuit breaker, and timeout support.
Shared across browser tasks, LLM calls, and pipeline steps.
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

from ghost_media_engine.logging import get_logger

logger = get_logger("Retry")

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class RetryPolicy:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    retryable_exceptions: tuple = (Exception,)
    timeout: Optional[float] = None


@dataclass
class CircuitBreaker:
    """
    Circuit breaker pattern to stop retrying after repeated failures.

    Usage:
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        if breaker.allow_request():
            try:
                result = await do_something()
                breaker.record_success()
            except Exception:
                breaker.record_failure()
                raise
    """
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False, repr=False)
    _failure_count: int = field(default=0, init=False, repr=False)
    _last_failure_time: float = field(default=0.0, init=False, repr=False)

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def allow_request(self) -> bool:
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker: OPEN -> HALF_OPEN (testing recovery)")
                return True
            return False
        if self._state == CircuitState.HALF_OPEN:
            return True
        return False

    def record_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            logger.success("Circuit breaker: HALF_OPEN -> CLOSED (recovered)")
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                f"Circuit breaker: OPEN (failures={self._failure_count}, "
                f"threshold={self.failure_threshold})"
            )

    def reset(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0


def _calculate_delay(attempt: int, policy: RetryPolicy) -> float:
    delay = min(
        policy.max_delay,
        policy.base_delay * (policy.exponential_base ** (attempt - 1))
    )
    jitter = delay * 0.1 * random.random()
    return delay + jitter


async def retry_async(
    func: Callable,
    *args,
    policy: Optional[RetryPolicy] = None,
    circuit_breaker: Optional[CircuitBreaker] = None,
    operation_name: str = "operation",
    **kwargs,
) -> Any:
    """
    Execute an async function with retry logic.

    Args:
        func: Async callable to execute
        policy: Retry configuration (default: 3 attempts, 1s base delay)
        circuit_breaker: Optional circuit breaker instance
        operation_name: Name for logging output
        *args, **kwargs: Arguments passed to func

    Returns:
        Result from func

    Raises:
        Last exception if all retries exhausted
    """
    if policy is None:
        policy = RetryPolicy()

    last_exception = None

    for attempt in range(1, policy.max_attempts + 1):
        if circuit_breaker and not circuit_breaker.allow_request():
            raise RuntimeError(
                f"Circuit breaker OPEN for {operation_name} "
                f"(failures={circuit_breaker.failure_count})"
            )

        try:
            if policy.timeout:
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=policy.timeout
                )
            else:
                result = await func(*args, **kwargs)

            if circuit_breaker:
                circuit_breaker.record_success()

            if attempt > 1:
                logger.success(f"{operation_name} succeeded on attempt {attempt}")
            return result

        except Exception as exc:
            last_exception = exc

            if circuit_breaker:
                circuit_breaker.record_failure()

            is_retryable = isinstance(exc, policy.retryable_exceptions)
            is_last_attempt = attempt == policy.max_attempts

            if not is_retryable or is_last_attempt:
                logger.error(
                    f"{operation_name} failed (attempt {attempt}/{policy.max_attempts}): "
                    f"{type(exc).__name__}: {exc}"
                )
                raise

            delay = _calculate_delay(attempt, policy)
            logger.warning(
                f"{operation_name} failed (attempt {attempt}/{policy.max_attempts}), "
                f"retrying in {delay:.1f}s: {type(exc).__name__}: {exc}"
            )
            await asyncio.sleep(delay)

    raise last_exception


def retry_sync(
    func: Callable,
    *args,
    policy: Optional[RetryPolicy] = None,
    circuit_breaker: Optional[CircuitBreaker] = None,
    operation_name: str = "operation",
    **kwargs,
) -> Any:
    """
    Execute a synchronous function with retry logic.

    Args:
        func: Synchronous callable to execute
        policy: Retry configuration (default: 3 attempts, 1s base delay)
        circuit_breaker: Optional circuit breaker instance
        operation_name: Name for logging output
        *args, **kwargs: Arguments passed to func

    Returns:
        Result from func

    Raises:
        Last exception if all retries exhausted
    """
    if policy is None:
        policy = RetryPolicy()

    last_exception = None

    for attempt in range(1, policy.max_attempts + 1):
        if circuit_breaker and not circuit_breaker.allow_request():
            raise RuntimeError(
                f"Circuit breaker OPEN for {operation_name} "
                f"(failures={circuit_breaker.failure_count})"
            )

        try:
            result = func(*args, **kwargs)

            if circuit_breaker:
                circuit_breaker.record_success()

            if attempt > 1:
                logger.success(f"{operation_name} succeeded on attempt {attempt}")
            return result

        except Exception as exc:
            last_exception = exc

            if circuit_breaker:
                circuit_breaker.record_failure()

            is_retryable = isinstance(exc, policy.retryable_exceptions)
            is_last_attempt = attempt == policy.max_attempts

            if not is_retryable or is_last_attempt:
                logger.error(
                    f"{operation_name} failed (attempt {attempt}/{policy.max_attempts}): "
                    f"{type(exc).__name__}: {exc}"
                )
                raise

            delay = _calculate_delay(attempt, policy)
            logger.warning(
                f"{operation_name} failed (attempt {attempt}/{policy.max_attempts}), "
                f"retrying in {delay:.1f}s: {type(exc).__name__}: {exc}"
            )
            time.sleep(delay)

    raise last_exception

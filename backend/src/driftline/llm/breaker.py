from collections import deque
from enum import Enum

from driftline.clock import Clock


class BreakerState(str, Enum):
    closed = "closed"
    open = "open"
    half_open = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        *,
        clock: Clock,
        failure_threshold: int = 5,
        error_rate_threshold: float = 0.5,
        window_seconds: float = 30.0,
        min_calls_in_window: int = 10,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._clock = clock
        self._failure_threshold = failure_threshold
        self._error_rate_threshold = error_rate_threshold
        self._window_seconds = window_seconds
        self._min_calls = min_calls_in_window
        self._cooldown = cooldown_seconds
        self._calls: deque[tuple[float, bool]] = deque()
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False

    @property
    def state(self) -> BreakerState:
        if self._opened_at is None:
            return BreakerState.closed
        if self._clock.now() - self._opened_at >= self._cooldown:
            return BreakerState.half_open
        return BreakerState.open

    def allow(self) -> bool:
        state = self.state
        if state is BreakerState.closed:
            return True
        if state is BreakerState.half_open and not self._probe_in_flight:
            self._probe_in_flight = True
            return True
        return False

    def record_success(self) -> None:
        if self.state is BreakerState.half_open:
            self._reset()
        self._consecutive_failures = 0
        self._record(True)

    def record_failure(self) -> None:
        if self.state is BreakerState.half_open:
            self._open()
            return
        self._consecutive_failures += 1
        self._record(False)
        if self._consecutive_failures >= self._failure_threshold or self._error_rate_exceeded():
            self._open()

    def _record(self, ok: bool) -> None:
        now = self._clock.now()
        self._calls.append((now, ok))
        while self._calls and now - self._calls[0][0] > self._window_seconds:
            self._calls.popleft()

    def _error_rate_exceeded(self) -> bool:
        if len(self._calls) < self._min_calls:
            return False
        failures = sum(1 for _, ok in self._calls if not ok)
        return failures / len(self._calls) >= self._error_rate_threshold

    def _open(self) -> None:
        self._opened_at = self._clock.now()
        self._probe_in_flight = False

    def _reset(self) -> None:
        self._opened_at = None
        self._probe_in_flight = False
        self._calls.clear()
        self._consecutive_failures = 0

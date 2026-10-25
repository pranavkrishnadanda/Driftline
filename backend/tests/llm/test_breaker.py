from driftline.clock import ManualClock
from driftline.llm.breaker import BreakerState, CircuitBreaker


def make(clock=None, **kw):
    return CircuitBreaker(clock=clock or ManualClock(0.0), **kw)


def test_starts_closed_and_allows():
    b = make()
    assert b.state is BreakerState.closed
    assert b.allow()


def test_opens_after_consecutive_failures():
    b = make(failure_threshold=5)
    for _ in range(4):
        b.record_failure()
    assert b.state is BreakerState.closed
    b.record_failure()
    assert b.state is BreakerState.open
    assert not b.allow()


def test_success_resets_consecutive_count():
    b = make(failure_threshold=3, min_calls_in_window=100)
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    b.record_failure()
    assert b.state is BreakerState.closed


def test_opens_on_error_rate_in_window():
    b = make(failure_threshold=100, error_rate_threshold=0.5, min_calls_in_window=10)
    for _ in range(5):
        b.record_success()
        b.record_failure()
    assert b.state is BreakerState.open


def test_old_calls_leave_the_window():
    clock = ManualClock(0.0)
    b = make(clock, failure_threshold=100, min_calls_in_window=10, window_seconds=30)
    for _ in range(9):
        b.record_failure()
    clock.advance(31)
    b.record_failure()
    assert b.state is BreakerState.closed


def test_half_open_after_cooldown_allows_single_probe():
    clock = ManualClock(0.0)
    b = make(clock, failure_threshold=1, cooldown_seconds=30)
    b.record_failure()
    assert not b.allow()
    clock.advance(30)
    assert b.state is BreakerState.half_open
    assert b.allow() is True
    assert b.allow() is False


def test_probe_success_closes():
    clock = ManualClock(0.0)
    b = make(clock, failure_threshold=1, cooldown_seconds=30)
    b.record_failure()
    clock.advance(30)
    assert b.allow()
    b.record_success()
    assert b.state is BreakerState.closed
    assert b.allow()


def test_probe_failure_reopens_for_another_cooldown():
    clock = ManualClock(0.0)
    b = make(clock, failure_threshold=1, cooldown_seconds=30)
    b.record_failure()
    clock.advance(30)
    assert b.allow()
    b.record_failure()
    assert b.state is BreakerState.open
    clock.advance(29)
    assert not b.allow()
    clock.advance(1)
    assert b.allow()

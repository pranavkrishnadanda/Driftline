import time

from driftline.clock import ManualClock, SystemClock


async def test_manual_clock_advances_on_sleep_and_advance():
    clock = ManualClock(start=100.0)
    assert clock.now() == 100.0
    clock.advance(2.5)
    assert clock.now() == 102.5
    await clock.sleep(1.5)
    assert clock.now() == 104.0


def test_system_clock_is_wall_clock():
    assert abs(SystemClock().now() - time.time()) < 1.0

import asyncio
import os
import time

import pytest

from driftline.health import heartbeat_loop, is_fresh, main, run_with_heartbeat


async def test_heartbeat_loop_touches_until_stopped(tmp_path):
    path = str(tmp_path / "beat")
    stop = asyncio.Event()
    task = asyncio.create_task(heartbeat_loop(path, stop, interval_s=0.01))
    while not os.path.exists(path):
        await asyncio.sleep(0.01)
    first = os.path.getmtime(path)
    os.utime(path, (first - 100, first - 100))
    while os.path.getmtime(path) < first - 50:  # the loop touches it again
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, 2)


def test_freshness_and_cli_exit_codes(tmp_path):
    path = str(tmp_path / "beat")
    assert not is_fresh(path, max_age_s=60)
    assert main(["--path", path]) == 1
    open(path, "w").close()
    assert is_fresh(path, max_age_s=60)
    assert main(["--path", path, "--max-age", "60"]) == 0
    old = time.time() - 120
    os.utime(path, (old, old))
    assert not is_fresh(path, max_age_s=60)
    assert main(["--path", path, "--max-age", "60"]) == 1


async def test_run_with_heartbeat_stops_the_beat_however_the_service_ends(tmp_path):
    path = str(tmp_path / "beat")

    async def returns_early() -> None:  # ends without anyone setting `stop`
        await asyncio.sleep(0)

    stop = asyncio.Event()
    await asyncio.wait_for(run_with_heartbeat(returns_early(), stop, path), 2)
    assert stop.is_set() and os.path.exists(path)

    async def crashes() -> None:
        raise RuntimeError("worker died")

    stop = asyncio.Event()
    with pytest.raises(RuntimeError, match="worker died"):
        await asyncio.wait_for(run_with_heartbeat(crashes(), stop, path), 2)
    assert stop.is_set()

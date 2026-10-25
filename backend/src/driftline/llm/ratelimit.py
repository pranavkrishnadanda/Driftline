from redis.asyncio import Redis

from driftline.clock import Clock

# KEYS[1] bucket hash; ARGV: capacity, refill_per_sec, cost, now
_LUA = """
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then
  tokens = capacity
  ts = now
end
local elapsed = math.max(0, now - ts)
tokens = math.min(capacity, tokens + elapsed * rate)
local allowed = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(math.max(now, ts)))
redis.call('EXPIRE', KEYS[1], math.ceil(capacity / rate) + 60)
local wait = 0
if allowed == 0 then
  wait = (cost - tokens) / rate
end
return {allowed, tostring(wait)}
"""


class RateLimitTimeout(Exception):
    pass


class RedisTokenBucket:
    """Token bucket shared by every worker that uses the same Redis key."""

    def __init__(
        self, redis: Redis, key: str, *, capacity: float, refill_per_sec: float, clock: Clock
    ) -> None:
        self.key = key
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self._clock = clock
        self._script = redis.register_script(_LUA)

    async def try_acquire(self, cost: float = 1.0) -> tuple[bool, float]:
        allowed, wait = await self._script(
            keys=[self.key], args=[self.capacity, self.refill_per_sec, cost, self._clock.now()]
        )
        return bool(int(allowed)), float(wait)

    async def acquire(self, cost: float = 1.0, *, timeout: float) -> None:
        if cost > self.capacity:
            raise ValueError(f"cost {cost} exceeds bucket capacity {self.capacity}")
        deadline = self._clock.now() + timeout
        while True:
            allowed, wait = await self.try_acquire(cost)
            if allowed:
                return
            if self._clock.now() + wait > deadline:
                raise RateLimitTimeout(f"{self.key}: needs {wait:.2f}s, timeout {timeout}s")
            await self._clock.sleep(wait)

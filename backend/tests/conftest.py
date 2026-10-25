import pytest
import redis.asyncio as aioredis
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer


@pytest.fixture(scope="session")
def pg_dsn():
    with PostgresContainer(
        "pgvector/pgvector:pg16", username="test", password="test", dbname="test", driver=None
    ) as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def redis_url():
    with RedisContainer("redis:7-alpine") as r:
        yield f"redis://{r.get_container_host_ip()}:{r.get_exposed_port(6379)}/0"


@pytest.fixture
async def redis_client(redis_url):
    client = aioredis.from_url(redis_url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()

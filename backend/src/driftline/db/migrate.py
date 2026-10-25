from pathlib import Path

from alembic import command
from alembic.config import Config

from driftline.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[3]


def _sqlalchemy_url(dsn: str) -> str:
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations(dsn: str, revision: str = "head") -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", _sqlalchemy_url(dsn))
    command.upgrade(cfg, revision)


if __name__ == "__main__":
    run_migrations(Settings().database_url)

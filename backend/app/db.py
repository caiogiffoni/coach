import importlib
from collections.abc import Generator

from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from alembic import command

from .config import BASE_DIR, DATA_DIR, settings

DATA_DIR.mkdir(exist_ok=True)

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

ALEMBIC_INI = BASE_DIR / "alembic.ini"
# Revision whose schema equals what `create_all` produced before Alembic existed.
BASELINE_REVISION = "3cdf8a5bc122"
# Every module that declares tables; Alembic autogenerate and the test
# `create_all` only see tables whose module has been imported.
MODEL_MODULES = (
    "app.models",
    "app.coaching.plan_models",
    "app.garmin.models",
    "app.ingestion.models",
    "app.profile.models",
    "app.workouts.models",
)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def import_all_models() -> None:
    """Register every table on ``Base.metadata``.

    Example:
        >>> import_all_models(); "users" in Base.metadata.tables
        True
    """
    for module_name in MODEL_MODULES:
        importlib.import_module(module_name)


def alembic_config(database_url: str) -> Config:
    """Build an Alembic config for ``database_url`` independent of the cwd.

    Example:
        >>> command.upgrade(alembic_config("sqlite:///coach.db"), "head")
    """
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BASE_DIR / "alembic"))
    # ConfigParser interpolates '%', so escape it (URL-encoded passwords).
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def is_unversioned_database(database_url: str) -> bool:
    """True when tables exist but Alembic never ran (DB made by ``create_all``)."""
    probe_engine = create_engine(database_url)
    try:
        table_names = set(inspect(probe_engine).get_table_names())
    finally:
        probe_engine.dispose()
    return bool(table_names) and "alembic_version" not in table_names


def upgrade_database(database_url: str = settings.database_url) -> None:
    """Bring the schema to ``head``, adopting pre-Alembic databases first.

    Legacy DBs created by ``Base.metadata.create_all`` already match the
    baseline revision, so they are stamped at it (not re-created) and then
    upgraded through any later revisions.

    Example:
        >>> upgrade_database("sqlite:///data/coach.db")
    """
    config = alembic_config(database_url)
    if is_unversioned_database(database_url):
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")

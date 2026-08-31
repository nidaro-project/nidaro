from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from nidaro.calendar import models as _calendar_models
from nidaro.commitments import models as _commitment_models
from nidaro.config import get_settings
from nidaro.connectors import models as _connector_models
from nidaro.conversations import models as _conversation_models
from nidaro.db.base import Base
from nidaro.household import models as _household_models
from nidaro.jobs import models as _job_models
from nidaro.memory import models as _memory_models
from nidaro.sources import models as _source_models
from nidaro.tasks import models as _task_models

_model_modules = (
    _calendar_models,
    _commitment_models,
    _connector_models,
    _conversation_models,
    _household_models,
    _job_models,
    _memory_models,
    _source_models,
    _task_models,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    import asyncio

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

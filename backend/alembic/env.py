import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from dotenv import load_dotenv

# Load .env from the backend directory
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.db.base import Base
import app.models.user      # noqa: F401 — ensures models are registered with Base
import app.models.sales     # noqa: F401 — registers sales pipeline models
import app.models.platform        # noqa: F401 — registers Space-based platform models
import app.models.creator_billing  # noqa: F401 — registers creator plan/subscription models
import app.models.payment          # noqa: F401 — registers payment transaction ledger
import app.models.payment_option   # noqa: F401 — registers payment options model
import app.models.payment_option_schedule  # noqa: F401 — registers payment option schedules
import app.models.access_pass      # noqa: F401 — registers access pass / booking credit model
import app.models.notification     # noqa: F401 — registers notification model

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

from app.core.config import get_settings
from app.core.db import Base
from app.services.models import Service
from app.integrations.models import ServiceIntegration
from app.workflows.models import Workflow

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata
import os, sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))  # añade backend/ al sys.path
from dotenv import load_dotenv
root = os.path.join(os.path.dirname(__file__), "..", "..")  # repo root
load_dotenv(os.path.join(root, ".env"))

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

from app.core.config import settings
from app.db.base import Base

# --------------------------------------------------------
# 1. Configuración general de Alembic
# --------------------------------------------------------
config = context.config

# Configurar el archivo de logs si existe
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --------------------------------------------------------
# 2. Importar metadatos de los modelos (Base.metadata)
# --------------------------------------------------------
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata

# --------------------------------------------------------
# 3. Definir URL de conexión desde tu .env
# --------------------------------------------------------
def get_url():
    return settings.DATABASE_URL

# --------------------------------------------------------
# 4. Modo OFFLINE (genera SQL sin conectarse)
# --------------------------------------------------------
def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,   # útil si cambias tipos
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # útil si cambias tipos
        )
        with context.begin_transaction():
            context.run_migrations()

# --------------------------------------------------------
# 6. Seleccionar modo
# --------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

from alembic import context
from sqlalchemy import create_engine
from models import Base, DATABASE_URL

config = context.config
target_metadata = Base.metadata

def run_migrations_online():
    connectable = create_engine(DATABASE_URL.replace("sqlite+aiosqlite", "sqlite"))
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    context.configure(url=DATABASE_URL)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()

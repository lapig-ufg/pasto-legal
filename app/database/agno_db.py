from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.utils.log import log_debug

from app.database.session import engine
from app.configs.config import config


if config.DATABASE_TYPE == 'sqlite':
    db = SqliteDb(db_engine=engine)
else:
    db = PostgresDb(db_engine=engine)
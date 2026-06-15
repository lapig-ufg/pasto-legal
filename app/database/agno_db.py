from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.utils.log import log_debug

from app.database.session import engine
from app.configs.config import config


if config.DATABASE_TYPE == 'sqlite':
    log_debug("\033[36mUsing SQLite database\033[0m")
    db = SqliteDb(db_engine=engine)
else:
    log_debug("\033[36Using Postgres database\033[0m")
    db = PostgresDb(db_engine=engine)
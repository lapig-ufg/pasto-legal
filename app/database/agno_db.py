from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb

from app.database.session import engine, DATABASE_TYPE


# Instancia o banco do Agno reaproveitando a engine central
if DATABASE_TYPE == 'sqlite':
    db = SqliteDb(db_engine=engine)
else:
    db = PostgresDb(db_engine=engine)
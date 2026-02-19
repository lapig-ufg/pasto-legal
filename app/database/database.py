import os

from pathlib import Path

from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb


DATABASE_TYPE = os.environ.get('DATABASE_TYPE', 'postgres').lower()

if DATABASE_TYPE == 'sqlite':
    tmp_path = Path("tmp")
    tmp_path.mkdir(exist_ok=True)
    
    db_url = f"sqlite:///{tmp_path}/agno.db"
    db = SqliteDb(db_url=db_url)
else:
    if not (POSTGRES_HOST := os.environ.get('POSTGRES_HOST')):
        raise ValueError("POSTGRES_HOST environment variables must be set.")
    if not (POSTGRES_PORT := os.environ.get('POSTGRES_PORT')):
        raise ValueError("POSTGRES_PORT environment variables must be set.")
    if not (POSTGRES_DBNAME := os.environ.get('POSTGRES_DBNAME')):
        raise ValueError("POSTGRES_DBNAME environment variables must be set.")
    if not (POSTGRES_USER := os.environ.get('POSTGRES_USER')):
        raise ValueError("POSTGRES_USER environment variables must be set.")
    if not (POSTGRES_PASSWORD := os.environ.get('POSTGRES_PASSWORD')):
        raise ValueError("POSTGRES_PASSWORD environment variables must be set.")

    db_url = f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DBNAME}"
    db = PostgresDb(db_url=db_url)
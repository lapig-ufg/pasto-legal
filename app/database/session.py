import os

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_TYPE = os.environ.get('DATABASE_TYPE', 'postgres').lower()

if DATABASE_TYPE == 'sqlite':
    tmp_path = Path("tmp")
    tmp_path.mkdir(exist_ok=True)
    db_url = f"sqlite:///{tmp_path}/agno.db"
    
    # engine para SQLite
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
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

    if not all([POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DBNAME, POSTGRES_USER, POSTGRES_PASSWORD]):
        raise ValueError("Todas as variáveis de ambiente POSTGRES_* devem estar configuradas.")

    db_url = f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DBNAME}"
    
    # engine para Postgres com pool_pre_ping para evitar conexões "fantasmas"
    engine = create_engine(db_url, pool_pre_ping=True)

# Sessão e Base para as suas tabelas customizadas
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
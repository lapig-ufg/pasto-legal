from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from api.configs.config import config

if config.DATABASE_TYPE == 'sqlite':
    tmp_path = Path.cwd() / Path("tmp")
    tmp_path.mkdir(exist_ok=True)

    db_url = f"sqlite:///{tmp_path}/agno.db"
    
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
else:
    db_url = f"postgresql+psycopg://{config.POSTGRES_USER}:{config.POSTGRES_PASSWORD}@{config.POSTGRES_HOST}:{config.POSTGRES_PORT}/{config.POSTGRES_DBNAME}"
    
    engine = create_engine(db_url, pool_pre_ping=True)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
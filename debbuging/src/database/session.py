import os

from dotenv import load_dotenv
from sshtunnel import SSHTunnelForwarder
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

if not (POSTGRES_HOST := os.environ.get('POSTGRES_HOST')):
    raise ValueError("POSTGRES_HOST environment variables must be set.")
if not (POSTGRES_PORT := int(os.environ.get('POSTGRES_PORT'))):
    raise ValueError("POSTGRES_PORT environment variables must be set.")
if not (POSTGRES_DBNAME := os.environ.get('POSTGRES_DBNAME')):
    raise ValueError("POSTGRES_DBNAME environment variables must be set.")
if not (POSTGRES_USER := os.environ.get('POSTGRES_USER')):
    raise ValueError("POSTGRES_USER environment variables must be set.")
if not (POSTGRES_PASSWORD := os.environ.get('POSTGRES_PASSWORD')):
    raise ValueError("POSTGRES_PASSWORD environment variables must be set.")

if not (SSH_HOST := os.environ.get('SSH_HOST')):
    raise ValueError("SSH_HOST environment variables must be set.")
if not (SSH_PORT := int(os.environ.get('SSH_PORT'))):
    raise ValueError("SSH_PORT environment variables must be set.")
if not (SSH_USER := os.environ.get('SSH_USER')):
    raise ValueError("SSH_USER environment variables must be set.")
if not (SSH_PASSWORD := os.environ.get('SSH_PASSWORD')):
    raise ValueError("SSH_PASSWORD environment variables must be set.")

server = SSHTunnelForwarder(
        (SSH_HOST, SSH_PORT),
        ssh_username=SSH_USER,
        ssh_password=SSH_PASSWORD,
        remote_bind_address=(POSTGRES_HOST, POSTGRES_PORT)
    )
server.start()

db_url = f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@127.0.0.1:{server.local_bind_port}/{POSTGRES_DBNAME}"

engine = create_engine(db_url, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
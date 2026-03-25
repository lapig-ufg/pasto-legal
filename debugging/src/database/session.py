import os

from dotenv import load_dotenv
from sshtunnel import SSHTunnelForwarder
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

# --- 1. VALIDAÇÃO DAS VARIÁVEIS DO BANCO DE DADOS (Obrigatórias) ---
if not (POSTGRES_HOST := os.environ.get('POSTGRES_HOST')):
    raise ValueError("POSTGRES_HOST environment variable must be set.")

postgres_port_str = os.environ.get('POSTGRES_PORT')
if not postgres_port_str:
    raise ValueError("POSTGRES_PORT environment variable must be set.")
POSTGRES_PORT = int(postgres_port_str)

if not (POSTGRES_DBNAME := os.environ.get('POSTGRES_DBNAME')):
    raise ValueError("POSTGRES_DBNAME environment variable must be set.")
if not (POSTGRES_USER := os.environ.get('POSTGRES_USER')):
    raise ValueError("POSTGRES_USER environment variable must be set.")
if not (POSTGRES_PASSWORD := os.environ.get('POSTGRES_PASSWORD')):
    raise ValueError("POSTGRES_PASSWORD environment variable must be set.")


# --- 2. VALIDAÇÃO DAS VARIÁVEIS SSH (Opcionais) ---
SSH_HOST = os.environ.get('SSH_HOST')
ssh_port_str = os.environ.get('SSH_PORT')
SSH_PORT = int(ssh_port_str) if ssh_port_str else None
SSH_USER = os.environ.get('SSH_USER')
SSH_PASSWORD = os.environ.get('SSH_PASSWORD')


# --- 3. CONFIGURAÇÃO DA CONEXÃO (Com ou sem túnel) ---
if SSH_HOST:
    if not all([SSH_PORT, SSH_USER, SSH_PASSWORD]):
        raise ValueError("If SSH_HOST is set, SSH_PORT, SSH_USER, and SSH_PASSWORD must also be set.")
    
    server = SSHTunnelForwarder(
        (SSH_HOST, SSH_PORT),
        ssh_username=SSH_USER,
        ssh_password=SSH_PASSWORD,
        remote_bind_address=(POSTGRES_HOST, POSTGRES_PORT)
    )
    server.start()
    
    db_host = "127.0.0.1"
    db_port = server.local_bind_port
    print(f"🔗 Conectando ao banco via Túnel SSH (Porta local: {db_port})")

else:
    db_host = POSTGRES_HOST
    db_port = POSTGRES_PORT
    print("🌐 Conectando ao banco diretamente (Sem túnel SSH)")

# --- 4. INICIALIZAÇÃO DO SQLALCHEMY ---
db_url = f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{db_host}:{db_port}/{POSTGRES_DBNAME}"

engine = create_engine(db_url, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
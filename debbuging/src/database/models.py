from sqlalchemy import Column, String, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from src.database.session import Base

class AgentSession(Base):
    __tablename__ = "agno_sessions"
    __table_args__ = {'schema': 'ai'}

    # Strings (varchar)
    session_id = Column(String, primary_key=True, nullable=False)
    session_type = Column(String, nullable=False)
    agent_id = Column(String)
    team_id = Column(String)
    workflow_id = Column(String)
    user_id = Column(String)

    # JSONB (Para os dados estruturados do seu mock)
    session_data = Column(JSONB)
    agent_data = Column(JSONB)
    team_data = Column(JSONB)
    workflow_data = Column(JSONB)
    meta_data = Column("metadata", JSONB) 
    runs = Column(JSONB)
    summary = Column(JSONB)

    # Inteiros 8 bytes (int8)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger)
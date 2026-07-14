import datetime
from sqlalchemy import Column, Integer, Text, String, DateTime, Boolean

from app.database.session import Base
from app.configs.config import config

class UserTermsAcceptance(Base):
    """Table that records the formal acceptance of the system's terms and conditions."""
    __tablename__ = "user_terms_acceptance"
    
    if config.DATABASE_TYPE != 'sqlite':
        __table_args__ = {'schema': 'ai'} 
    user_id = Column(String, primary_key=True, index=True, comment="Unique identifier (e.g., wa:5511999999999)")
    accepted = Column(Boolean, default=False, nullable=False, comment="Flag indicating acceptance")
    accepted_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, comment="Date and time of formal acceptance")
    
    
class NegativeFeedback(Base):
    __tablename__ = 'negative_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    original_question = Column(Text)
    reason_frustration = Column(Text)
    desired_answer = Column(Text)
    context = Column(Text)


class PositiveFeedback(Base):
    __tablename__ = 'positive_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    user_message = Column(Text)
    assistant_response = Column(Text)
    handler_message = Column(Text)
    grade = Column(Integer)
    context = Column(Text)


class AnalysisFeedback(Base):
    __tablename__ = 'analysis_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    original_question = Column(Text)
    desired_analysis = Column(Text)
    context = Column(Text)



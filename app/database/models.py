from sqlalchemy import Column, Integer, Text

from app.database.session import Base


class FrustrationFeedback(Base):
    __tablename__ = 'frustration_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    original_question = Column(Text)
    reason_frustration = Column(Text)
    desired_answer = Column(Text)

class AnalysisFeedback(Base):
    __tablename__ = 'analysis_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    original_question = Column(Text)
    desired_analysis = Column(Text)
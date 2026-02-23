from sqlalchemy import Column, Integer, Text

from app.database.session import Base


class Feedback(Base):
    __tablename__ = 'feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    pergunta_original = Column(Text)
    motivo_frustracao = Column(Text)
    resposta_desejada = Column(Text)
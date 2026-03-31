from sqlalchemy import Column, Integer, String, Text, DateTime
from database import Base
import datetime

class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    authors = Column(String, nullable=True)
    journal = Column(String, nullable=True)
    doi = Column(String, nullable=True)
    status = Column(String, default="toread") # "toread", "reading", "used"
    
    # AI Summary fields
    abstract = Column(Text, nullable=True)
    keywords = Column(Text, nullable=True)
    methodology = Column(Text, nullable=True)
    key_findings = Column(Text, nullable=True)
    limitations = Column(Text, nullable=True)
    simplified_text = Column(Text, nullable=True)
    
    # Personal Notes
    personal_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

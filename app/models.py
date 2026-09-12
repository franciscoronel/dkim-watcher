from sqlalchemy import Column, Integer, String, DateTime, Boolean, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import os
Base = declarative_base()

class DKIMRecord(Base):
    __tablename__ = "dkim_records"
    id = Column(Integer, primary_key=True)
    domain = Column(String, index=True)
    selector = Column(String, index=True)
    txt = Column(String)
    key_length = Column(Integer)
    last_checked = Column(DateTime, default=datetime.utcnow)
    changed_at = Column(DateTime)
    unchanged_for = Column(Integer)
    changed = Column(Boolean, default=False)

class DKIMSelector(Base):
    __tablename__ = "dkim_selectors"
    id = Column(Integer, primary_key=True)
    domain = Column(String, index=True)
    selector = Column(String, index=True)
    last_checked = Column(DateTime)

# SQLite in the project root
DB_PATH = "/opt/data/db/dkim.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db():
    Base.metadata.create_all(bind=engine)

"""
Database setup.

We use SQLite through SQLAlchemy as the storage backend. SQLite is a
pure Python-friendly, file-based database that requires no separate
DB server process, which fits the "DB is Python" requirement for this
prototype. The DB file lives under /data so it can be mounted as a
Docker volume and survive container restarts.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DB_DIR = os.environ.get("APP_DATA_DIR", "/data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "portal.db")

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

# check_same_thread=False is required because FastAPI may use the
# session across different threads within a single request/worker.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from typing import Generator
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

if settings.sqlalchemy_database_url.startswith("sqlite"):
    engine = create_engine(
        settings.sqlalchemy_database_url,
        connect_args=settings.sqlalchemy_connect_args,
    )
else:
    engine = create_engine(
        settings.sqlalchemy_database_url,
        connect_args=settings.sqlalchemy_connect_args,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=10,
        max_overflow=20
    )


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a SQLAlchemy database session and ensures cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> bool:
    """Check if the database connection can be established."""
    try:
        with engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error(f"Database connection error: {exc}")
        return False

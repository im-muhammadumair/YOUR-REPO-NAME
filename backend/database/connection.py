"""Database connection and session management using SQLAlchemy ORM.

The connection string is read from the DATABASE_URL environment variable (see
config.py). Because all data access goes through the ORM, switching databases
(e.g. to PostgreSQL or Oracle) only requires changing DATABASE_URL and adding
the matching driver - no query code changes.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import DATABASE_CONNECT_ARGS, DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args=DATABASE_CONNECT_ARGS, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a database session.

    Takes: none.
    Returns: a generator yielding a database session.
    Side effect: the session is always closed when the request finishes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

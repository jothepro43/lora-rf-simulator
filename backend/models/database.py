import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/nodes.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    os.makedirs("data", exist_ok=True)
    # Check if existing tables have the right schema; if not, recreate
    try:
        from sqlalchemy import inspect
        inspector = inspect(engine)
        if inspector.has_table("nodes"):
            existing_cols = {col['name'] for col in inspector.get_columns('nodes')}
            from models.node import Node
            expected_cols = {col.name for col in Node.__table__.columns}
            missing = expected_cols - existing_cols
            if missing:
                import logging
                logging.getLogger(__name__).warning(
                    f"Database schema outdated (missing columns: {missing}). "
                    f"Recreating tables...")
                Base.metadata.drop_all(bind=engine)
    except Exception:
        pass
    Base.metadata.create_all(bind=engine)

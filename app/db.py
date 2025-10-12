from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

# Create engine with connection pool configuration
engine = create_engine(
    settings.DATABASE_URL,
    echo=False,  # Set to True for SQL debugging
    pool_pre_ping=True,  # Verify connections before using
    pool_size=10,  # Number of connections to keep open
    max_overflow=20,  # Maximum connections beyond pool_size
    pool_recycle=3600,  # Recycle connections after 1 hour
    pool_timeout=30,  # Seconds to wait before giving up on getting a connection
    connect_args={
        "connect_timeout": 10,  # Connection timeout in seconds
        "application_name": "pnl_api"  # Identify connections in DB
    }
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

# Dependency for FastAPI endpoints
def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

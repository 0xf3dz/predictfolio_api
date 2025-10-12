from sqlalchemy import Column, String, Float, DateTime, Integer, Index
from datetime import datetime
from app.db import Base

class UserPnL(Base):
    """Stores pre-computed realized PnL for each user"""
    __tablename__ = "user_pnl"
    
    user_address = Column(String, primary_key=True, index=True)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    position_count = Column(Integer, nullable=False, default=0)
    last_subgraph_sync = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<UserPnL(user={self.user_address}, pnl=${self.realized_pnl:.2f})>"


class PnLHistory(Base):
    """Stores historical PnL snapshots for analytics"""
    __tablename__ = "pnl_history"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_address = Column(String, nullable=False, index=True)
    realized_pnl = Column(Float, nullable=False)
    unrealized_pnl = Column(Float, nullable=False)
    total_pnl = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Composite index for efficient queries
    __table_args__ = (
        Index('idx_user_timestamp', 'user_address', 'timestamp'),
    )
    
    def __repr__(self):
        return f"<PnLHistory(user={self.user_address}, total=${self.total_pnl:.2f}, time={self.timestamp})>"
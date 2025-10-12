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

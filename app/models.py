from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class PnLResponse(BaseModel):
    user_address: str
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    realized_position_count: int
    unrealized_position_count: int
    realized_last_updated: Optional[str] = None  # NEW: when realized was last fetched
    cached: bool
    cache_age_seconds: Optional[int] = None
    
class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
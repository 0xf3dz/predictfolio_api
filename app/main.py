from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import time
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from app.config import settings
from app.models import PnLResponse, ErrorResponse
from app.db import get_db, engine, Base
from app.db_models import UserPnL, PnLHistory
from app.services.subgraph import get_realized_pnl
from app.services.polymarket import get_unrealized_pnl

# Initialize FastAPI
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description="Calculate Polymarket PnL for any user"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create database tables on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
  # Startup
  print("🚀 Creating database tables...")
  Base.metadata.create_all(bind=engine)
  print("✅ Database tables created successfully!")
  yield
  # Shutdown
  pass

    
@app.get("/")
def root():
    return {
        "message": "Polymarket PnL API",
        "version": settings.API_VERSION,
        "endpoints": {
            "pnl": "/api/pnl/{user_address}",
            "refresh": "/api/pnl/{user_address}/refresh",
            "health": "/health"
        }
    }

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/api/pnl/{user_address}", response_model=PnLResponse)
@app.get("/api/pnl/{user_address}/", response_model=PnLResponse)
async def get_pnl(
    user_address: str,
    force_refresh: bool = Query(False, description="Force refresh from subgraph"),
    db: Session = Depends(get_db)
):
    """
    Get total PnL for a Polymarket user
    
    - **user_address**: Ethereum address (0x...)
    - **force_refresh**: Force refresh realized PnL from subgraph
    """
    
    # Normalize address
    user_address = user_address.lower()
    
    # Validate address format
    if not user_address.startswith('0x') or len(user_address) != 42:
        raise HTTPException(status_code=400, detail="Invalid Ethereum address")
    
    # Get or compute realized PnL
    user_pnl = db.query(UserPnL).filter(UserPnL.user_address == user_address).first()
    
    # Decide if we need to refresh from subgraph
    should_refresh = (
        force_refresh or 
        user_pnl is None or
        (datetime.utcnow() - user_pnl.last_subgraph_sync) > timedelta(minutes=30)
    )
    
    if should_refresh:
        print(f"Fetching realized PnL from subgraph for {user_address}...")
        try:
            # Fetch from subgraph
            realized_data = get_realized_pnl(user_address)
            realized_pnl = realized_data['realized_pnl']
            realized_count = realized_data['position_count']
            
            # Update or create in database
            if user_pnl:
                user_pnl.realized_pnl = realized_pnl
                user_pnl.position_count = realized_count
                user_pnl.last_subgraph_sync = datetime.utcnow()
                user_pnl.updated_at = datetime.utcnow()
            else:
                user_pnl = UserPnL(
                    user_address=user_address,
                    realized_pnl=realized_pnl,
                    position_count=realized_count,
                    last_subgraph_sync=datetime.utcnow()
                )
                db.add(user_pnl)
            
            db.commit()
            db.refresh(user_pnl)
            print(f"✅ Stored realized PnL in database: ${realized_pnl:.2f}")
            
        except Exception as e:
            db.rollback()
            print(f"Error fetching from subgraph: {e}")
            # If we have old data, use it; otherwise fail
            if user_pnl:
                print(f"⚠️ Using cached data from database")
            else:
                raise HTTPException(status_code=500, detail=f"Error fetching PnL: {str(e)}")
    
    # Get realized PnL from database
    realized_pnl = user_pnl.realized_pnl
    realized_count = user_pnl.position_count
    last_updated = user_pnl.last_subgraph_sync
    
    # Always fetch fresh unrealized PnL
    try:
        unrealized_data = get_unrealized_pnl(user_address)
        unrealized_pnl = unrealized_data['unrealized_pnl']
        unrealized_count = unrealized_data['position_count']
    except Exception as e:
        print(f"Error fetching unrealized PnL: {e}")
        # Graceful degradation - return with 0 unrealized
        unrealized_pnl = 0
        unrealized_count = 0
    
    # Calculate total
    total_pnl = realized_pnl + unrealized_pnl
    
    # Save snapshot to history
    try:
        history = PnLHistory(
            user_address=user_address,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_pnl=total_pnl
        )
        db.add(history)
        db.commit()
    except Exception as e:
        print(f"Error saving to history: {e}")
        db.rollback()
    
    return {
        'user_address': user_address,
        'realized_pnl': round(realized_pnl, 2),
        'unrealized_pnl': round(unrealized_pnl, 2),
        'total_pnl': round(total_pnl, 2),
        'realized_position_count': realized_count,
        'unrealized_position_count': unrealized_count,
        'realized_last_updated': last_updated.isoformat(),
        'cached': not should_refresh
    }

@app.post("/api/pnl/{user_address}/refresh")
async def refresh_pnl(
    user_address: str,
    db: Session = Depends(get_db)
):
    """Manually trigger a refresh for this user"""
    user_address = user_address.lower()
    
    if not user_address.startswith('0x') or len(user_address) != 42:
        raise HTTPException(status_code=400, detail="Invalid Ethereum address")
    
    try:
        # Fetch fresh data
        realized_data = get_realized_pnl(user_address)
        
        # Update database
        user_pnl = db.query(UserPnL).filter(UserPnL.user_address == user_address).first()
        
        if user_pnl:
            user_pnl.realized_pnl = realized_data['realized_pnl']
            user_pnl.position_count = realized_data['position_count']
            user_pnl.last_subgraph_sync = datetime.utcnow()
            user_pnl.updated_at = datetime.utcnow()
        else:
            user_pnl = UserPnL(
                user_address=user_address,
                realized_pnl=realized_data['realized_pnl'],
                position_count=realized_data['position_count']
            )
            db.add(user_pnl)
        
        db.commit()
        
        return {
            "message": "Refreshed successfully",
            "user_address": user_address,
            "realized_pnl": realized_data['realized_pnl'],
            "last_updated": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history/{user_address}")
async def get_history(
    user_address: str,
    limit: int = Query(100, description="Number of records to return"),
    db: Session = Depends(get_db)
):
    """Get historical PnL snapshots for a user"""
    user_address = user_address.lower()
    
    history = db.query(PnLHistory)\
        .filter(PnLHistory.user_address == user_address)\
        .order_by(PnLHistory.timestamp.desc())\
        .limit(limit)\
        .all()
    
    return {
        "user_address": user_address,
        "count": len(history),
        "history": [
            {
                "timestamp": h.timestamp.isoformat(),
                "realized_pnl": h.realized_pnl,
                "unrealized_pnl": h.unrealized_pnl,
                "total_pnl": h.total_pnl
            }
            for h in history
        ]
    }

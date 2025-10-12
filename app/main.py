from fastapi import FastAPI, HTTPException, Query, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import time
from datetime import datetime, timedelta
import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Optional

from app.config import settings
from app.models import PnLResponse, ErrorResponse
from app.db import get_db, engine, Base
from app.db_models import UserPnL
from app.services.subgraph import get_realized_pnl
from app.services.polymarket import get_unrealized_pnl
from app.cache import cache

# Timeout configuration
ENDPOINT_TIMEOUT = 60.0  # 60 seconds total timeout for /api/pnl endpoint
REFRESH_TIMEOUT = 90.0   # 90 seconds for refresh endpoint (more intensive)

# Rate limiting configuration
RATE_LIMIT_PER_MINUTE = settings.RATE_LIMIT_PER_MINUTE
RATE_LIMIT_WINDOW = 60  # 60 seconds window

# Thread pool for running blocking operations
thread_pool = ThreadPoolExecutor(max_workers=10)

# Initialize FastAPI
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description="""
    
Calculate Polymarket PnL for any user
    
## Features
- **Realized PnL**: Historical profit/loss from closed positions (Goldsky)
- **Unrealized PnL**: Current profit/loss from open positions (https://data-api.polymarket.com/positions)
- **Force Refresh**: On-demand data updates from subgraph

## Performance
- **Redis Caching**: 10-minute cache for unrealized data
- **Postgres db**: 30-minute refresh for realized data

## Notes
- Database is updated on-demand during API requests. There are no background jobs
- API is currently rate limited to 300 requests per minute
"""
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting middleware using Redis"""
    
    # Skip rate limiting for health checks
    if request.url.path == "/health" or request.url.path == "/":
        return await call_next(request)
    
    # Get client IP
    client_ip = request.client.host
    
    # Create rate limit key
    current_minute = int(time.time() // 60)
    rate_limit_key = f"rate_limit:{client_ip}:{current_minute}"
    
    try:
        # Get current count from Redis
        current_count = cache.redis_client.get(rate_limit_key)
        current_count = int(current_count) if current_count else 0
        
        # Check if rate limit exceeded
        if current_count >= RATE_LIMIT_PER_MINUTE:
            import json
            return Response(
                content=json.dumps({
                    "error": "Rate limit exceeded",
                    "message": f"Maximum {RATE_LIMIT_PER_MINUTE} requests per minute allowed",
                    "retry_after": 60 - (int(time.time()) % 60)
                }),
                status_code=429,
                media_type="application/json"
            )
        
        # Increment counter
        cache.redis_client.incr(rate_limit_key)
        cache.redis_client.expire(rate_limit_key, RATE_LIMIT_WINDOW)
        
        # Call next middleware/endpoint
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT_PER_MINUTE)
        response.headers["X-RateLimit-Remaining"] = str(RATE_LIMIT_PER_MINUTE - current_count - 1)
        response.headers["X-RateLimit-Reset"] = str((current_minute + 1) * 60)
        
        return response
        
    except Exception as e:
        # If Redis fails, allow the request but log the error
        print(f"Rate limiting error: {e}")
        return await call_next(request)

# Create database tables on startup
@app.on_event("startup")
def startup_event():
    """Create database tables on startup"""
    print("🚀 Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created successfully!")

# Cleanup thread pool on shutdown
@app.on_event("shutdown")
def shutdown_event():
    """Cleanup resources on shutdown"""
    print("🛑 Shutting down thread pool...")
    thread_pool.shutdown(wait=False)
    print("✅ Thread pool shutdown complete!")

# Simple circuit breaker for external services
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def can_execute(self):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                return True
            return False
        return True
    
    def record_success(self):
        self.failures = 0
        self.state = "CLOSED"
    
    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.state = "OPEN"

# Circuit breaker instances
subgraph_circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
polymarket_circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30)

# Rate limiting dependency for user-specific endpoints
def get_user_rate_limit(
    request: Request,
    user_address: str,
    requests_per_minute: int = RATE_LIMIT_PER_MINUTE
):
    """Dependency for user-specific rate limiting"""
    
    # Create user-specific rate limit key
    current_minute = int(time.time() // 60)
    user_rate_limit_key = f"user_rate_limit:{user_address}:{current_minute}"
    
    try:
        # Get current count from Redis
        current_count = cache.redis_client.get(user_rate_limit_key)
        current_count = int(current_count) if current_count else 0
        
        # Check if rate limit exceeded
        if current_count >= requests_per_minute:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "User rate limit exceeded",
                    "message": f"Maximum {requests_per_minute} requests per minute allowed for this user",
                    "retry_after": 60 - (int(time.time()) % 60)
                }
            )
        
        # Increment counter
        cache.redis_client.incr(user_rate_limit_key)
        cache.redis_client.expire(user_rate_limit_key, RATE_LIMIT_WINDOW)
        
    except Exception as e:
        # If Redis fails, log but allow the request
        print(f"User rate limiting error: {e}")

# Helper functions for timeout-protected operations
async def run_with_timeout(func, *args, timeout=ENDPOINT_TIMEOUT):
    """Run a blocking function with timeout protection"""
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(thread_pool, func, *args),
            timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Operation timed out after {timeout} seconds. Please try again later."
        )

def fetch_pnl_data(user_address: str, force_refresh: bool, db: Session):
    """Core PnL data fetching logic (blocking operation)"""
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
        
        # Check circuit breaker
        if not subgraph_circuit_breaker.can_execute():
            print("⚠️ Subgraph circuit breaker OPEN - using cached data")
            if user_pnl:
                # Use cached data if available
                should_refresh = False
            else:
                raise HTTPException(
                    status_code=503,
                    detail="Subgraph service temporarily unavailable. Please try again later."
                )
        
        try:
            # Fetch from subgraph
            realized_data = get_realized_pnl(user_address)
            realized_pnl = realized_data['realized_pnl']
            realized_count = realized_data['position_count']
            
            # Record success in circuit breaker
            subgraph_circuit_breaker.record_success()
            
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
            
            # Record failure in circuit breaker
            subgraph_circuit_breaker.record_failure()
            
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
    # Check circuit breaker
    if not polymarket_circuit_breaker.can_execute():
        print("⚠️ Polymarket API circuit breaker OPEN - using 0 unrealized")
        unrealized_pnl = 0
        unrealized_count = 0
    else:
        try:
            unrealized_data = get_unrealized_pnl(user_address)
            unrealized_pnl = unrealized_data['unrealized_pnl']
            unrealized_count = unrealized_data['position_count']
            
            # Record success in circuit breaker
            polymarket_circuit_breaker.record_success()
        except Exception as e:
            print(f"Error fetching unrealized PnL: {e}")
            
            # Record failure in circuit breaker
            polymarket_circuit_breaker.record_failure()
            
            # Graceful degradation - return with 0 unrealized
            unrealized_pnl = 0
            unrealized_count = 0
    
    # Calculate total
    total_pnl = realized_pnl + unrealized_pnl
    
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
    
@app.get("/")
def root():
    return {
        "message": "Polymarket PnL API TEST",
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
async def get_pnl(
    request: Request,
    user_address: str,
    force_refresh: bool = Query(False, description="Force refresh from subgraph"),
    db: Session = Depends(get_db)
):
    """
    Get total PnL for a Polymarket user
    
    - **user_address**: Ethereum address (0x...)
    - **force_refresh**: Force refresh realized PnL from subgraph
    """
    
    # Apply user-specific rate limiting
    get_user_rate_limit(request, user_address)
    
    try:
        # Run the core logic with timeout protection
        result = await run_with_timeout(
            fetch_pnl_data, 
            user_address, 
            force_refresh, 
            db,
            timeout=ENDPOINT_TIMEOUT
        )
        return result
    except HTTPException:
        # Re-raise HTTP exceptions (like 400, 500, 504)
        raise
    except Exception as e:
        # Catch any unexpected errors
        print(f"Unexpected error in get_pnl: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Internal server error. Please try again later."
        )

def refresh_pnl_data(user_address: str, db: Session):
    """Core refresh logic (blocking operation)"""
    user_address = user_address.lower()
    
    if not user_address.startswith('0x') or len(user_address) != 42:
        raise HTTPException(status_code=400, detail="Invalid Ethereum address")
    
    # Check circuit breaker
    if not subgraph_circuit_breaker.can_execute():
        raise HTTPException(
            status_code=503,
            detail="Subgraph service temporarily unavailable. Please try again later."
        )
    
    # Fetch fresh data
    try:
        realized_data = get_realized_pnl(user_address)
        # Record success in circuit breaker
        subgraph_circuit_breaker.record_success()
    except Exception as e:
        # Record failure in circuit breaker
        subgraph_circuit_breaker.record_failure()
        raise e
    
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

@app.post("/api/pnl/{user_address}/refresh")
async def refresh_pnl(
    request: Request,
    user_address: str,
    db: Session = Depends(get_db)
):
    """Manually trigger a refresh for this user"""
    
    # Apply stricter rate limiting for refresh endpoint (half the normal limit)
    get_user_rate_limit(request, user_address, requests_per_minute=RATE_LIMIT_PER_MINUTE // 2)
    
    try:
        # Run refresh with timeout protection
        result = await run_with_timeout(
            refresh_pnl_data,
            user_address,
            db,
            timeout=REFRESH_TIMEOUT
        )
        return result
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Catch any unexpected errors
        print(f"Unexpected error in refresh_pnl: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Internal server error during refresh. Please try again later."
        )

import requests
from typing import Dict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def create_retry_session():
    """Create a requests session with retry logic"""
    session = requests.Session()
    
    # Configure retry strategy
    retry_strategy = Retry(
        total=2,  # Maximum number of retries
        backoff_factor=1,  # Wait 1, 2 seconds between retries
        status_forcelist=[429, 500, 502, 503, 504],  # Retry on these status codes
        allowed_methods=["GET"]
    )
    
    # Mount adapter with retry strategy
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

def get_unrealized_pnl(user_address: str) -> Dict:
    """
    Calculate total cash PnL from Polymarket API
    """
    # Import settings here
    from app.config import settings
    
    url = settings.POLYMARKET_API
    
    querystring = {
        "user": user_address,
        "sizeThreshold": "1",  # Filter out tiny positions
        "limit": "500",
        "sortBy": "TOKENS",
        "sortDirection": "DESC"
    }
    
    # Create retry session
    session = create_retry_session()
    
    try:
        response = session.get(url, params=querystring, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Handle different response formats
        if isinstance(data, dict):
            positions = data.get('positions') or data.get('data') or []
        elif isinstance(data, list):
            positions = data
        else:
            positions = []
        
        def safe_num(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return 0.0
        
        # Sum all cashPnl
        total_cash_pnl = sum(safe_num(p.get('cashPnl')) for p in positions)
        
        # FIXED: Return a Dict instead of just a float
        return {
            'unrealized_pnl': total_cash_pnl,
            'position_count': len(positions)
        }
        
    except requests.exceptions.RequestException as e:
        print(f"Polymarket API error: {e}")
        raise  # FIXED: added error handling

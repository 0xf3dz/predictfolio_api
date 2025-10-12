import requests
from typing import Dict

def get_unrealized_pnl(user_address: str) -> Dict:
    """
    Calculate total cash PnL from Polymarket API
    """
    # Import settings here
    from app.config import settings
    
    url = settings.POLYMARKET_API  # FIXED: use settings instead of hardcoded
    
    querystring = {
        "user": user_address,
        "sizeThreshold": "1",  # FIXED: uncommented and set to "1" to filter out tiny positions
        "limit": "500",
        "sortBy": "TOKENS",
        "sortDirection": "DESC"
    }
    
    try:
        response = requests.get(url, params=querystring, timeout=10)
        response.raise_for_status()  # FIXED: added error checking
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
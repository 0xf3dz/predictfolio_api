import requests
import time
from typing import Dict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def create_retry_session():
    """Create a requests session with retry logic"""
    session = requests.Session()
    
    # Configure retry strategy
    retry_strategy = Retry(
        total=3,  # Maximum number of retries
        backoff_factor=1,  # Wait 1, 2, 4 seconds between retries
        status_forcelist=[429, 500, 502, 503, 504],  # Retry on these status codes
        allowed_methods=["POST", "GET"]
    )
    
    # Mount adapter with retry strategy
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

def get_realized_pnl(user_address: str, debug: bool = False) -> Dict:
    """Calculate total realized PnL with proper error handling"""
    
    # Import settings here
    from app.config import settings
    
    all_positions = []
    seen_ids = set()
    last_id = ""
    iterations = 0
    max_iterations = 50
    
    # Create retry session for all subgraph calls
    session = create_retry_session()
    
    while iterations < max_iterations:
        iterations += 1
        
        query = """
        query {
          userPositions(
            where: { 
              user: "%s"
              id_gt: "%s"
            }
            first: 1000
            orderBy: id
            orderDirection: asc
          ) {
            id
            realizedPnl
          }
        }
        """ % (user_address.lower(), last_id)
        
        try:
            resp = session.post(
                settings.PNL_SUBGRAPH,
                json={"query": query}, 
                timeout=30
            )
            resp.raise_for_status()
            
            data = resp.json()
            
            if 'errors' in data:
                raise RuntimeError(f"Subgraph returned GraphQL errors: {data['errors']}")
            
            positions = data.get('data', {}).get('userPositions', [])
            
        except requests.exceptions.Timeout as error:
            raise RuntimeError("Subgraph request timed out") from error

        except requests.exceptions.RequestException as error:
            raise RuntimeError("Subgraph request failed") from error
        
        if not positions:
            if debug:
                print(f"No more positions at iteration {iterations}")
            break
        
        # Check for duplicates
        new_positions = []
        duplicates = 0
        for pos in positions:
            if pos['id'] in seen_ids:
                duplicates += 1
                if debug:
                    print(f"⚠️  Duplicate ID found: {pos['id']}")
            else:
                seen_ids.add(pos['id'])
                new_positions.append(pos)
        
        if duplicates > 0:
            print(f"⚠️  Found {duplicates} duplicate positions at iteration {iterations}")
        
        all_positions.extend(new_positions)
        last_id = positions[-1]['id']
        
        if debug and iterations % 10 == 0:
            print(f"Iteration {iterations}: Fetched {len(positions)} positions, {len(new_positions)} new, total={len(all_positions)}")
        
        if len(positions) < 1000:
            if debug:
                print(f"Reached end at iteration {iterations}")
            break
        
        time.sleep(0.1)
    
    if iterations >= max_iterations and len(positions) == 1000:
        raise RuntimeError(f"Subgraph pagination exceeded {max_iterations} pages")
    
    if debug:
        print(f"\n{'='*60}")
        print(f"Pagination complete:")
        print(f"  Total iterations: {iterations}")
        print(f"  Unique positions: {len(all_positions)}")
        print(f"  Seen IDs: {len(seen_ids)}")
        print(f"{'='*60}\n")
    
    # Sum all realized PnL
    total_realized = sum(int(pos['realizedPnl']) for pos in all_positions)
    total_realized_dollars = total_realized / 1e6
    
    # FIXED: Return a Dict instead of just a float
    return {
        'realized_pnl': total_realized_dollars,
        'position_count': len(all_positions),
        'iterations': iterations
    }

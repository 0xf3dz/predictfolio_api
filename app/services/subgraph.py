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
            market {
              id
              resolved
              resolvedAt
            }
            closedAt
            outcomeIndex
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
                print(f"GraphQL Error at iteration {iterations}: {data['errors']}")
                break
            
            positions = data.get('data', {}).get('userPositions', [])
            
        except requests.exceptions.Timeout:
            print(f"Timeout at iteration {iterations}, retrying...")
            time.sleep(2)
            continue
            
        except requests.exceptions.RequestException as e:
            print(f"Request error at iteration {iterations}: {e}")
            break
        
        if not positions:
            if debug:
                print(f"No more positions at iteration {iterations}")
            break
        
        # Check for duplicates and filter redemptions
        new_positions = []
        duplicates = 0
        redemptions_filtered = 0
        
        for pos in positions:
            if pos['id'] in seen_ids:
                duplicates += 1
                if debug:
                    print(f"⚠️  Duplicate ID found: {pos['id']}")
                continue
            
            # Filter out redemption artifacts
            market = pos.get('market', {})
            if market.get('resolved'):
                resolved_at = market.get('resolvedAt')
                closed_at = pos.get('closedAt')
                
                if resolved_at and closed_at:
                    try:
                        # Skip positions closed after market resolution (redemptions)
                        if int(closed_at) > int(resolved_at):
                            redemptions_filtered += 1
                            if debug:
                                print(f"⚠️  Filtered redemption: position {pos['id']} closed after market resolution")
                            continue
                    except (ValueError, TypeError):
                        # If timestamp parsing fails, include the position to be safe
                        if debug:
                            print(f"⚠️  Could not parse timestamps for position {pos['id']}, including in PnL")
            
            seen_ids.add(pos['id'])
            new_positions.append(pos)
        
        if duplicates > 0:
            print(f"⚠️  Found {duplicates} duplicate positions at iteration {iterations}")
        
        if redemptions_filtered > 0:
            print(f"⚠️  Filtered {redemptions_filtered} redemption artifacts at iteration {iterations}")
        
        all_positions.extend(new_positions)
        last_id = positions[-1]['id']
        
        if debug and iterations % 10 == 0:
            print(f"Iteration {iterations}: Fetched {len(positions)} positions, {len(new_positions)} new, total={len(all_positions)}")
        
        if len(positions) < 1000:
            if debug:
                print(f"Reached end at iteration {iterations}")
            break
        
        time.sleep(0.1)
    
    if iterations >= max_iterations:
        print(f"⚠️  WARNING: Hit max iterations ({max_iterations}). May not have all positions!")
    
    if debug:
        total_redemptions = sum(1 for pos in all_positions 
                              if pos.get('market', {}).get('resolved') and 
                                 pos.get('closedAt') and pos.get('market', {}).get('resolvedAt') and
                                 int(pos.get('closedAt', 0)) > int(pos.get('market', {}).get('resolvedAt', 0)))
        
        print(f"\n{'='*60}")
        print(f"Pagination complete:")
        print(f"  Total iterations: {iterations}")
        print(f"  Unique positions: {len(all_positions)}")
        print(f"  Redemptions filtered: {total_redemptions}")
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

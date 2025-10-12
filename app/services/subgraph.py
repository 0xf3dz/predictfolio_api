import requests
import time
from typing import Dict

def get_realized_pnl(user_address: str, debug: bool = False) -> Dict:
    """Calculate total realized PnL with proper error handling"""
    
    # Import settings here
    from app.config import settings
    
    all_positions = []
    seen_ids = set()
    last_id = ""
    iterations = 0
    max_iterations = 300
    
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
            resp = requests.post(
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
    
    if iterations >= max_iterations:
        print(f"⚠️  WARNING: Hit max iterations ({max_iterations}). May not have all positions!")
    
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

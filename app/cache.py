import redis
import json
from typing import Optional, Any
from app.config import settings

class Cache:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True
        )
    
    def get(self, key: str) -> Optional[dict]:
        """Get cached value"""
        try:
            data = self.redis_client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            print(f"Cache get error: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: int = settings.CACHE_TTL_SECONDS):
        """Set cached value with TTL"""
        try:
            self.redis_client.setex(key, ttl, json.dumps(value))
        except Exception as e:
            print(f"Cache set error: {e}")
    
    def delete(self, key: str):
        """Delete cached value"""
        try:
            self.redis_client.delete(key)
        except Exception as e:
            print(f"Cache delete error: {e}")

cache = Cache()
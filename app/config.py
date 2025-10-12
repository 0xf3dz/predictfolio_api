from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API Settings
    API_TITLE: str = "Polymarket PnL API"
    API_VERSION: str = "1.0.0"
    
    # External APIs
    PNL_SUBGRAPH: str = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/pnl-subgraph/0.0.14/gn"
    POLYMARKET_API: str = "https://data-api.polymarket.com/positions"
    
    # Database
    DATABASE_URL: str = "postgresql://pnl_user:pnl_password@localhost:5432/pnl_db"    
    
    # Cache Settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_URL: str = ""  # For Railway/cloud deployments
    CACHE_TTL_SECONDS: int = 300
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 10
    
    class Config:
        env_file = ".env"

settings = Settings()

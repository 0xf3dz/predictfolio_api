# Polymarket PNL API

Polymarket PNL API calculates realized and unrealized profit and loss for a Polymarket address.

- Realized profit and loss comes from the Goldsky PnL subgraph.
- Unrealized profit and loss comes from the Polymarket Data API.
- PostgreSQL stores realized results for 30 minutes.
- Redis stores unrealized results for five minutes and supports rate limits.

## Requirements

- Python 3.11
- PostgreSQL
- Redis

## Start the API

1. Create and activate a Python virtual environment.

   ```bash
   python3.11 -m venv venv
   source venv/bin/activate
   ```

2. Install the dependencies.

   ```bash
   pip install -r requirements.txt
   ```

3. Start PostgreSQL and Redis.

   ```bash
   docker run --rm --name predictfolio-postgres \
     -e POSTGRES_USER=pnl_user \
     -e POSTGRES_PASSWORD=pnl_password \
     -e POSTGRES_DB=pnl_db \
     -p 5432:5432 postgres:16-alpine
   ```

   Run Redis in a second terminal.

   ```bash
   docker run --rm --name predictfolio-redis \
     -p 6379:6379 redis:7-alpine
   ```

4. Set the service configuration.

   ```bash
   export DATABASE_URL='postgresql://pnl_user:pnl_password@localhost:5432/pnl_db'
   export REDIS_URL='redis://localhost:6379/0'
   ```

5. Start the API.

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

6. Open the API documentation at http://localhost:8000/docs.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://pnl_user:pnl_password@localhost:5432/pnl_db` | PostgreSQL connection URL |
| `REDIS_URL` | Empty | Complete Redis connection URL |
| `REDIS_HOST` | `localhost` | Redis host when `REDIS_URL` is empty |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_DB` | `0` | Redis database number |
| `CACHE_TTL_SECONDS` | `600` | Default cache duration in seconds |
| `RATE_LIMIT_PER_MINUTE` | `300` | Request limit for each minute |
| `PNL_SUBGRAPH` | Public Goldsky endpoint | Realized profit and loss source |
| `POLYMARKET_API` | Polymarket positions endpoint | Unrealized profit and loss source |

A `.env` file can supply these values during local development.

## API endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Show API information |
| `GET` | `/health` | Show API health |
| `GET` | `/api/pnl/{user_address}` | Get realized, unrealized, and total profit and loss |
| `POST` | `/api/pnl/{user_address}/refresh` | Refresh realized profit and loss |

Use `force_refresh=true` on the `GET` request to update realized data before the response.

```bash
curl 'http://localhost:8000/api/pnl/0x0000000000000000000000000000000000000000'
```

The address must contain `0x` and 40 hexadecimal characters.

## Test the API

Run the behavior tests.

```bash
python -m unittest discover -s tests -v
```

Check the dependency set for known vulnerabilities.

```bash
uvx pip-audit -r requirements.txt
```

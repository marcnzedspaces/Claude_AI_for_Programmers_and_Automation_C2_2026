from typing import Any

from pymongo import AsyncMongoClient

from app.config import get_settings


# One shared client/database reference
# Module-level so every request reuses the same connection pool. They start
# as None, meaning "not connected yet".
_client: AsyncMongoClient | None = None
_database: Any = None


# Called once at application startup (see lifespan in main.py).
async def connect_to_database() -> None:
    # Create the shared MongoDB client and verify connectivity.
    global _client, _database

    if _client is not None:
        return

    settings = get_settings()
    client = AsyncMongoClient(
        settings.mongodb_uri.get_secret_value()
    )

    try:
        # Test the connection by pinging the server
        await client.admin.command("ping")
    except Exception:
        # The server is unreachable or rejected us: release the client's
        # resources and let the error stop startup.
        await client.close()
        raise

    # Only store the references once the ping has succeeded, so a failed
    # connection never leaves a half-working client behind.
    _client = client
    _database = client[settings.mongodb_database]


async def ping_database() -> None:
    # Verify that the active client can reach MongoDB.
    if _client is None:
        raise RuntimeError("Database has not been connected.")

    await _client.admin.command("ping")


# Used by routes to get the shared database handle.
def get_database() -> Any:
    # Return the configured application database.
    # Fail with a clear message if startup never connected (for example,
    # when used outside the running app).
    if _database is None:
        raise RuntimeError("Database has not been connected.")

    return _database


# Called once at application shutdown (see lifespan in main.py).
async def close_database() -> None:
    # Close the shared MongoDB client during shutdown.
    global _client, _database

    if _client is not None:
        await _client.close()

    _client = None
    _database = None

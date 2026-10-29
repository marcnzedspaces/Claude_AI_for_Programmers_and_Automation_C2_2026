from fastapi import APIRouter

from app.schemas.common import HealthResponse


# Health check: lets you (or a monitoring tool) confirm the API is running.
# It does not call Claude or MongoDB.
router = APIRouter(tags=["health"])


# GET /health: returns {"status": "ok"} when the server is up.
@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")

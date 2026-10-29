from fastapi import APIRouter, Query

from app.database import get_database
from app.repositories.usage_repository import UsageRepository
from app.schemas.usage import (
    AIOperation,
    UsageResponse,
)
from app.services.usage_service import UsageService


# Routes only accept the request and shape the response. UsageService and the
# repository do the work.
router = APIRouter(
    prefix="/usage",
    tags=["usage"],
)


# GET /usage: list AI usage logs, newest first, with a summary of the same logs.
# Every filter is optional; no filter means all usage logs.
@router.get(
    "",
    response_model=UsageResponse,
)
# FastAPI checks each query parameter from the URL (type, length, range) before this function runs.
# Invalid values get a 422 reply automatically.
async def get_usage(
    operation: AIOperation | None = Query(
        default=None,
    ),
    model: str | None = Query(
        default=None,
        min_length=1,
        max_length=100,
    ),
    request_id: str | None = Query(
        default=None,
        min_length=3,
        max_length=100,
    ),
    ticket_id: str | None = Query(
        default=None,
        min_length=3,
        max_length=50,
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    skip: int = Query(
        default=0,
        ge=0,
    ),
) -> UsageResponse:
    # Build the service for this request. Flow: route -> service -> repository -> database.
    service = UsageService(
        UsageRepository(get_database())
    )

    # The route only passes the validated values on; the service decides what to do with them.
    return await service.query(
        operation=operation,
        model=model,
        request_id=request_id,
        ticket_id=ticket_id,
        limit=limit,
        skip=skip,
    )

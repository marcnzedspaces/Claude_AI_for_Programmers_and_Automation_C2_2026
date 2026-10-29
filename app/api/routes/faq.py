from fastapi import APIRouter, Request

from app.database import get_database
from app.repositories.faq_repository import FAQRepository
from app.repositories.usage_repository import UsageRepository
from app.schemas.faq import FAQAskRequest, FAQAskResponse
from app.schemas.usage import AIOperation, AIUsage
from app.services.claude_service import ClaudeService
from app.services.faq_service import FAQService
from app.services.usage_service import UsageService


# All endpoints in this file live under /faq.
router = APIRouter(
    prefix="/faq",
    tags=["faq"],
)


# POST /faq/ask: answer a customer question using only approved FAQs,
# then record the Claude usage.
@router.post(
    "/ask",
    response_model=FAQAskResponse,
)
async def ask_faq(
    request: FAQAskRequest,
    http_request: Request,
) -> FAQAskResponse:
    # Routes only wire things together; the services do the real work.
    database = get_database()
    claude_service = ClaudeService()
    usage_service = UsageService(
        UsageRepository(database)
    )

    # Compose the service from the Claude and MongoDB boundaries.
    service = FAQService(
        claude_service=claude_service,
        faq_repository=FAQRepository(database),
    )

    # Close the per-request Claude client even if answering fails.
    try:
        result = await service.ask(request.question)
    finally:
        await claude_service.close()

    # No Claude call means there is no usage record for this response.
    usage = None

    if result.model is not None:
        # Put the numbers into the AIUsage shape shared by the usage log and the response.
        usage = AIUsage(
            model=result.model,
            input_tokens=result.input_tokens or 0,
            output_tokens=result.output_tokens or 0,
            latency_ms=result.latency_ms or 0,
        )

        # safe_record: failing to save usage must not break the customer's answer.
        await usage_service.safe_record(
            request_id=http_request.state.request_id,
            operation=AIOperation.FAQ_ANSWER,
            usage=usage,
        )

    # Only validated, approved data goes back to the client.
    return FAQAskResponse(
        answer=result.answer,
        sources=result.sources,
        requires_human_review=result.requires_human_review,
        usage=usage,
    )

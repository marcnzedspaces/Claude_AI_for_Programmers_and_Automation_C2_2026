from fastapi import APIRouter, Request, status

from app.database import get_database
from app.repositories.faq_repository import FAQRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.ticket_repository import TicketRepository
from app.repositories.usage_repository import UsageRepository
from app.schemas.usage import AIOperation
from app.schemas.workflow import (
    ProcessTicketRequest,
    ProcessTicketResponse,
)
from app.services.analysis_service import AnalysisService
from app.services.claude_service import ClaudeService
from app.services.response_service import ResponseService
from app.services.ticket_service import TicketService
from app.services.usage_service import UsageService
from app.services.workflow_service import WorkflowService


# route -> WorkflowService -> (AnalysisService, repositories, ResponseService,
# TicketService) -> MongoDB / Claude
# The route only builds the services and shapes the response. The order of the
# steps lives in WorkflowService, not here.
# prefix="/workflows" is added to every path in this file, and tags=["workflows"]
# groups the endpoints together in the /docs page.
router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
)


# POST /workflows/process-ticket: send a customer message and get back the
# stored ticket, a draft reply, and the list of steps that actually ran.
# 201 Created because the workflow creates a new ticket in the database.
@router.post(
    "/process-ticket",
    response_model=ProcessTicketResponse,
    status_code=status.HTTP_201_CREATED,
)
async def process_ticket(
    request: ProcessTicketRequest,
    http_request: Request,
) -> ProcessTicketResponse:
    # request is already validated by ProcessTicketRequest at this point.
    # The route obtains the shared database; it never queries MongoDB itself.
    database = get_database()
    # One ClaudeService is shared by the analysis and response steps, so the
    # route can close its HTTP connections once at the end.
    claude_service = ClaudeService()
    usage_service = UsageService(
        UsageRepository(database)
    )

    # Compose the deterministic workflow from existing services/repositories.
    service = WorkflowService(
        analysis_service=AnalysisService(claude_service),
        response_service=ResponseService(claude_service),
        ticket_service=TicketService(
            TicketRepository(database)
        ),
        order_repository=OrderRepository(database),
        faq_repository=FAQRepository(database),
    )

    try:
        # Runs the whole multi-step workflow (see WorkflowService.process).
        result = await service.process(request)
    finally:
        # Close the per-request Claude client even if a step fails.
        await claude_service.close()

    await usage_service.safe_record(
        request_id=http_request.state.request_id,
        operation=AIOperation.TICKET_ANALYSIS,
        usage=result.analysis_usage,
        ticket_id=result.ticket.ticket_id,
    )
    await usage_service.safe_record(
        request_id=http_request.state.request_id,
        operation=AIOperation.RESPONSE_GENERATION,
        usage=result.response_usage,
        ticket_id=result.ticket.ticket_id,
    )

    # The response exposes both the resulting ticket and the executed steps.
    return ProcessTicketResponse(
        ticket=result.ticket,
        executed_steps=result.executed_steps,
        analysis_usage=result.analysis_usage,
        response_usage=result.response_usage,
    )

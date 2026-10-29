from datetime import datetime, timezone

from app.core.ids import new_ticket_id
from app.repositories.ticket_repository import TicketRepository
from app.schemas.ai import TicketAnalysis
from app.schemas.common import (
    Priority,
    TicketCategory,
    TicketStatus,
)
from app.schemas.ticket import (
    TicketCreateRequest,
    TicketListResponse,
    TicketResponse,
)


# Use-case logic for tickets: decide the status, build the ticket and save it
# through the repository.
class TicketService:
    def __init__(
        self,
        ticket_repository: TicketRepository,
    ) -> None:
        self.ticket_repository = ticket_repository

    def determine_status(
        self,
        analysis: TicketAnalysis,
    ) -> TicketStatus:
        # The application, not Claude, decides the workflow status.
        if (
            analysis.needs_human_review
            or analysis.priority == Priority.URGENT
        ):
            return TicketStatus.NEEDS_HUMAN_REVIEW

        return TicketStatus.ANALYSED

    async def create(
        self,
        request: TicketCreateRequest,
        analysis: TicketAnalysis,
    ) -> TicketResponse:
        now = datetime.now(timezone.utc)

        # The application, not Claude or the client, sets the ID, status and timestamps.
        ticket = TicketResponse(
            ticket_id=new_ticket_id(),
            customer_id=request.customer_id,
            order_id=request.order_id,
            message=request.message,
            analysis=analysis,
            order_context=None,
            faq_context=[],
            # No draft yet; a later step can add one.
            draft_response=None,
            status=self.determine_status(analysis),
            # Only keep a reason when the application sent it for review.
            escalation_reason=None,
            processing_error=None,
            created_at=now,
            updated_at=now,
        )

        return await self.ticket_repository.insert(ticket)

    async def save(
        self,
        ticket: TicketResponse,
    ) -> TicketResponse:
        # Overwrite the stored ticket with this version.
        return await self.ticket_repository.replace(ticket)

    # None means "not found"; the route decides whether that is a 404.
    async def get(
        self,
        ticket_id: str,
    ) -> TicketResponse | None:
        return await self.ticket_repository.get_by_id(
            ticket_id
        )

    # Defined last: inside the class body, `list` now names this method,
    # so earlier annotations such as list[dict] must come before it.
    async def list(
        self,
        *,
        customer_id: str | None = None,
        status: TicketStatus | None = None,
        category: TicketCategory | None = None,
        limit: int = 20,
        skip: int = 0,
    ) -> TicketListResponse:
        items, total = await self.ticket_repository.list(
            customer_id=customer_id,
            status=status,
            category=category,
            limit=limit,
            skip=skip,
        )

        return TicketListResponse(
            items=items,
            total=total,
            limit=limit,
            skip=skip,
        )

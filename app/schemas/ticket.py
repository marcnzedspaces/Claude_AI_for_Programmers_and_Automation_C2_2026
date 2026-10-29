from datetime import datetime

from pydantic import Field

from app.schemas.ai import TicketAnalysis
from app.schemas.common import StrictModel, TicketStatus
from app.schemas.faq import FAQSource
from app.schemas.order import OrderContext


class TicketCreateRequest(StrictModel):
    # User/application inentifiers arrive with the support request
    customer_id: str = Field(
        min_length=3,
        max_length=50,
    )
    order_id: str | None = Field(
        default=None,
        max_length=50,
    )
    message: str = Field(
        min_length=5,
        max_length=5000,
    )


# A stored ticket: the customer's request, Claude's analysis and the application's workflow data.
class TicketResponse(StrictModel):
    ticket_id: str
    customer_id: str
    order_id: str | None
    message: str
    analysis: TicketAnalysis
    order_context: OrderContext | None = None
    faq_context: list[FAQSource] = Field(
        default_factory=list,
    )
    draft_response: str | None = None
    # Application-owned workflow state, not set by Claude
    status: TicketStatus
    escalation_reason: str | None = None
    processing_error: str | None = None
    created_at: datetime
    updated_at: datetime


class TicketListResponse(StrictModel):
    # Return pagination metadata along with the list of tickets
    items: list[TicketResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    skip: int = Field(ge=0)

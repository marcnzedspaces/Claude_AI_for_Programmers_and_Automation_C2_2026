from enum import Enum
from typing import Any

from pydantic import Field

from app.schemas.common import StrictModel
from app.schemas.ticket import TicketResponse
from app.schemas.usage import AIUsage


# Only names in this enum are capabilities the application knows about.
class ToolName(str, Enum):
    GET_ORDER_STATUS = "get_order_status"
    SEARCH_FAQ = "search_faq"
    ESCALATE_TICKET = "escalate_ticket"


# Argument models, one per tool. ToolRegistry turns each into the JSON schema
# that tells Claude what to send, and also uses it to validate what Claude
# actually sends. Claude-proposed arguments still pass through application
# validation, because model output is untrusted.
class GetOrderStatusArgs(StrictModel):
    order_id: str = Field(
        min_length=3,
        max_length=50,
    )


# Arguments for search_faq: the text to look up in the approved FAQ records.
class SearchFAQArgs(StrictModel):
    query: str = Field(
        min_length=3,
        max_length=200,
    )


# Arguments for escalate_ticket: why a human should take over. There is no
# ticket_id field on purpose; the registry always uses the current ticket.
class EscalateTicketArgs(StrictModel):
    reason: str = Field(
        min_length=5,
        max_length=300,
    )


# Body of POST /agent/support. customer_id is required because every data
# lookup is scoped to a customer; order_id is optional.
class AgentSupportRequest(StrictModel):
    customer_id: str = Field(
        min_length=3,
        max_length=50,
    )
    order_id: str | None = Field(
        default=None,
        min_length=3,
        max_length=50,
    )
    message: str = Field(
        min_length=5,
        max_length=5000,
    )


# One entry per tool call in the response, so a reader can check exactly what
# the agent did. This is the application's own record, not Claude's account.
class ToolExecutionAudit(StrictModel):
    # Record what the model requested and what the application actually did.
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    success: bool
    result_summary: str = Field(
        min_length=1,
        max_length=500,
    )


# Reply of POST /agent/support: the saved ticket, the customer-facing answer,
# the tool audit, and token usage. Usage is split in two so the cost of the
# analysis call and of the agent loop can be compared.
class AgentSupportResponse(StrictModel):
    ticket: TicketResponse
    final_response: str = Field(
        min_length=1,
        max_length=5000,
    )
    tool_calls: list[ToolExecutionAudit] = Field(
        default_factory=list,
    )
    # Bound the visible iteration count to the intended small teaching loop.
    iterations: int = Field(
        ge=1,
        le=4,
    )
    analysis_usage: AIUsage
    agent_usage: AIUsage

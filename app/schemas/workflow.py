from enum import Enum

from pydantic import Field

from app.schemas.common import StrictModel
from app.schemas.ticket import TicketResponse
from app.schemas.usage import AIUsage


# The steps the fixed workflow can run; executed_steps reports which ones ran.
class WorkflowStep(str, Enum):
    ANALYSIS = "analysis"
    ORDER_LOOKUP = "order_lookup"
    FAQ_LOOKUP = "faq_lookup"
    DATABASE_INSERT = "database_insert"
    RESPONSE_GENERATION = "response_generation"
    DATABASE_UPDATE = "database_update"


# Request body for POST /workflows/process-ticket.
class ProcessTicketRequest(StrictModel):
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


# Response: the stored ticket, the steps that ran, and the token usage of each Claude call.
class ProcessTicketResponse(StrictModel):
    ticket: TicketResponse
    # Debugging and understand ing the workflow execution
    executed_steps: list[WorkflowStep]
    analysis_usage: AIUsage
    response_usage: AIUsage

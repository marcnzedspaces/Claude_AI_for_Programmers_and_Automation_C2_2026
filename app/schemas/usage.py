from datetime import datetime
from enum import Enum

from pydantic import Field

from app.schemas.common import StrictModel


# The kinds of Claude call we track. An Enum accepts only these values,
# both in the database and in the ?operation= filter of GET /usage.
class AIOperation(str, Enum):
    TICKET_ANALYSIS = "ticket_analysis"
    RESPONSE_GENERATION = "response_generation"
    FAQ_ANSWER = "faq_answer"
    AGENT_DECISION = "agent_decision"


# What a Claude call reports about itself: the model and its token counts.
# The application adds everything else in AIUsageLog.
class AIUsage(StrictModel):
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)


# One row in the ai_usage_logs collection, i.e. one Claude call.
# The application fills in the IDs, total, cost and timestamp.
class AIUsageLog(StrictModel):
    usage_id: str = Field(min_length=3, max_length=50)
    request_id: str = Field(min_length=3, max_length=100)
    # Optional: some calls (for example a plain FAQ question) do not belong to a ticket.
    ticket_id: str | None = Field(
        default=None,
        max_length=50,
    )
    operation: AIOperation
    model: str = Field(min_length=1, max_length=100)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)
    created_at: datetime


# Totals across ALL logs that match the filters, not just the current page.
class UsageSummary(StrictModel):
    total_calls: int = Field(ge=0)
    total_input_tokens: int = Field(ge=0)
    total_output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    # An estimate from token counts and configured prices, not a real bill.
    estimated_cost_usd: float = Field(ge=0)
    average_latency_ms: float = Field(ge=0)


# The shape GET /usage returns: a summary, one page of logs, and paging details.
class UsageResponse(StrictModel):
    summary: UsageSummary
    items: list[AIUsageLog]
    # total counts every matching log; items only holds one page of them.
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    skip: int = Field(ge=0)

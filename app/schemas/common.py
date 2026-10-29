from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    # Base model for application-facing data contracts.

    # extra="forbid" rejects unknown fields; str_strip_whitespace trims spaces around text.
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


# Enums limit a field to a fixed set of values, so Pydantic rejects anything else.
class TicketCategory(str, Enum):
    DELIVERY = "delivery"
    RETURN = "return"
    REFUND = "refund"
    BILLING = "billing"
    PRODUCT = "product"
    ACCOUNT = "account"
    GENERAL = "general"
    OTHER = "other"


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


# Workflow state of a ticket. Set by the application, never by Claude.
class TicketStatus(str, Enum):
    NEW = "new"
    ANALYSED = "analysed"
    PROCESSED = "processed"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    ESCALATED = "escalated"
    PROCESSING_FAILED = "processing_failed"
    CLOSED = "closed"


# Response shape for GET /health.
class HealthResponse(StrictModel):
    status: Literal["ok"]

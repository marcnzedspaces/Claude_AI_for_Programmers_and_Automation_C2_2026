from pydantic import Field, model_validator

from app.schemas.common import (
    Priority,
    Sentiment,
    StrictModel,
    TicketCategory,
)
from app.schemas.usage import AIUsage


# Body of POST /summarise. The length limits reject empty/tiny input and
# cap very large input (which would also raise the cost).
class SummariseRequest(StrictModel):
    text: str = Field(
        min_length=20,
        max_length=5000,
    )


# Reply of POST /summarise: the summary plus token counts for cost tracking.
class SummariseResponse(StrictModel):
    summary: str
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


# Body of POST /analyse: the raw customer support message.
class AnalyseRequest(StrictModel):
    message: str = Field(
        min_length=5,
        max_length=5000,
    )


# The structured result Claude must return for a support ticket. Because the
# model output is untrusted, these constraints are checked before the data
# is used anywhere else in the application.
class TicketAnalysis(StrictModel):
    # Short one-line description of the ticket.
    summary: str = Field(
        min_length=5,
        max_length=300,
    )

    # Fixed-choice fields (enums), so Claude cannot invent new values.
    category: TicketCategory
    sentiment: Sentiment
    priority: Priority

    needs_order_lookup: bool
    # Flags that tell the backend which next steps are needed. The
    # developer's code, not Claude, decides what to do with them.
    needs_faq_lookup: bool
    needs_human_review: bool

    # Optional details; only required when the matching flag is True
    # (enforced by validate_dependencies below).
    faq_query: str | None = Field(
        default=None,
        max_length=200,
    )

    human_review_reason: str | None = Field(
        default=None,
        max_length=500,
    )

    @model_validator(mode="after")
    def validate_dependencies(self) -> "TicketAnalysis":
        # A FAQ lookup needs something to search for.
        if self.needs_faq_lookup and not self.faq_query:
            raise ValueError(
                "faq_query is required when needs_faq_lookup is true"
            )

        # A human reviewer needs to know why the ticket was escalated.
        if self.needs_human_review and not self.human_review_reason:
            raise ValueError(
                "human_review_reason is required when "
                "needs_human_review is true"
            )

        return self


# Reply of POST /analyse: the validated analysis plus token usage.
class AnalyseResponse(StrictModel):
    analysis: TicketAnalysis
    usage: AIUsage


# Body of POST /generate-response: the customer message to answer.
class GenerateResponseRequest(StrictModel):
    customer_message: str = Field(
        min_length=5,
        max_length=5000,
    )
    customer_id: str | None = Field(
        default=None,
        min_length=3,
        max_length=50,
    )
    order_id: str | None = Field(
        default=None,
        min_length=3,
        max_length=50,
    )
    # Caller supplies identifiers; the repository still verifies approval.
    faq_ids: list[str] = Field(
        default_factory=list,
        max_length=3,
    )

    # Cross-field rule that a single Field() cannot express. mode="after"
    # runs once every field has passed its own validation.
    @model_validator(mode="after")
    def validate_order_context(self) -> "GenerateResponseRequest":
        # If an order_id is provided, the request must also include a customer_id.
        if self.order_id and not self.customer_id:
            raise ValueError(
                "customer_id is required when order_id is supplied"
            )

        return self


class ResponseContextUsed(StrictModel):
    # Report the trusted context actually retrieved, not IDs merely requested.
    order_id: str | None = None
    faq_ids: list[str] = Field(default_factory=list)


# Reply of POST /generate-response: the draft text for a human to review,
# plus token usage. min_length=1 rejects an empty draft.
class GenerateResponseResponse(StrictModel):
    draft_response: str = Field(min_length=1, max_length=5000)
    context_used: ResponseContextUsed
    usage: AIUsage

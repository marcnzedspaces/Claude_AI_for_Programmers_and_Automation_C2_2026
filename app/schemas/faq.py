from pydantic import Field

from app.schemas.common import StrictModel, TicketCategory
from app.schemas.usage import AIUsage


# One approved FAQ entry: the only FAQ shape Claude may use as evidence.
class FAQSource(StrictModel):
    faq_id: str = Field(min_length=3, max_length=50)
    category: TicketCategory
    question: str = Field(min_length=3, max_length=500)
    answer: str = Field(min_length=3, max_length=2000)


# What Claude must return when answering from FAQs.
# supported_by_sources says whether the sources really back the answer.
class FAQAnswerDecision(StrictModel):
    answer: str = Field(min_length=1, max_length=2000)
    supported_by_sources: bool


# Request body for POST /faq/ask.
class FAQAskRequest(StrictModel):
    question: str = Field(
        min_length=5,
        max_length=1000,
    )


# Response for POST /faq/ask; usage is None when Claude was not called.
class FAQAskResponse(StrictModel):
    answer: str = Field(min_length=1, max_length=2000)
    sources: list[FAQSource] = Field(default_factory=list)
    requires_human_review: bool
    usage: AIUsage | None = None

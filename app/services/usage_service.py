import logging
from datetime import datetime, timezone

from pymongo.errors import PyMongoError

from app.config import get_settings
from app.core.ids import new_usage_id
from app.core.logging import log_event
from app.repositories.usage_repository import UsageRepository
from app.schemas.usage import (
    AIOperation,
    AIUsage,
    AIUsageLog,
    UsageResponse,
    UsageSummary,
)


# Use-case logic for AI usage tracking: build usage logs, price them, save them and report on them.
# Routes and other services call this class; only the repository touches MongoDB.
class UsageService:
    def __init__(
        self,
        repository: UsageRepository,
    ) -> None:
        self.repository = repository
        self.settings = get_settings()

    # Cost = tokens / 1 million * price per million tokens, worked out for input and output separately.
    # Prices come from settings (.env), not code, so they can change without editing code.
    def estimate_cost_usd(
        self,
        usage: AIUsage,
    ) -> float:
        input_cost = (
            usage.input_tokens
            / 1_000_000
            * self.settings.claude_input_cost_per_million_usd
        )
        output_cost = (
            usage.output_tokens
            / 1_000_000
            * self.settings.claude_output_cost_per_million_usd
        )

        # Round to 8 decimals to avoid long floating-point tails.
        return round(
            input_cost + output_cost,
            8,
        )

    # Builds and saves one usage log. The * makes the parameters keyword-only, so calls are easy to read.
    async def record(
        self,
        *,
        request_id: str,
        operation: AIOperation,
        usage: AIUsage,
        ticket_id: str | None = None,
    ) -> AIUsageLog:
        # The application decides the IDs, totals, cost and timestamp.
        # Only the model name and token counts originate from Claude's response.
        record = AIUsageLog(
            usage_id=new_usage_id(),
            request_id=request_id,
            ticket_id=ticket_id,
            operation=operation,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=(
                usage.input_tokens
                + usage.output_tokens
            ),
            latency_ms=usage.latency_ms,
            estimated_cost_usd=(
                self.estimate_cost_usd(usage)
            ),
            # Store time in UTC to avoid time-zone confusion.
            created_at=datetime.now(timezone.utc),
        )

        inserted = await self.repository.insert(record)

        log_event(
            "ai_usage",
            request_id=request_id,
            ticket_id=ticket_id,
            operation=operation.value,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=usage.latency_ms,
            estimated_cost_usd=(
                inserted.estimated_cost_usd
            ),
        )

        return inserted

    # Same as record(), but a database failure is logged instead of raised.
    # Use it when tracking usage must never break the user's request (the Claude call already succeeded).
    async def safe_record(
        self,
        *,
        request_id: str,
        operation: AIOperation,
        usage: AIUsage,
        ticket_id: str | None = None,
    ) -> AIUsageLog | None:
        try:
            return await self.record(
                request_id=request_id,
                operation=operation,
                usage=usage,
                ticket_id=ticket_id,
            )
        # Only database errors are swallowed; any other error is a real bug and should still surface.
        except PyMongoError:
            # Also write a log line, so usage shows up in the application logs.
            log_event(
                "ai_usage_persist_failed",
                level=logging.WARNING,
                request_id=request_id,
                ticket_id=ticket_id,
                operation=operation.value,
            )
            return None

    # Used by GET /usage: one page of logs plus a summary of all matching logs.
    async def query(
        self,
        *,
        operation: AIOperation | None = None,
        model: str | None = None,
        request_id: str | None = None,
        ticket_id: str | None = None,
        limit: int = 20,
        skip: int = 0,
    ) -> UsageResponse:
        items, total = await self.repository.list(
            operation=operation,
            model=model,
            request_id=request_id,
            ticket_id=ticket_id,
            limit=limit,
            skip=skip,
        )

        # Same filters as above, so the summary describes the same set of logs (not only this page).
        summary_data = await self.repository.summarize(
            operation=operation,
            model=model,
            request_id=request_id,
            ticket_id=ticket_id,
        )

        # Turn the repository's plain numbers into the validated UsageSummary.
        return UsageResponse(
            summary=UsageSummary(
                total_calls=int(
                    summary_data["total_calls"]
                ),
                total_input_tokens=int(
                    summary_data[
                        "total_input_tokens"
                    ]
                ),
                total_output_tokens=int(
                    summary_data[
                        "total_output_tokens"
                    ]
                ),
                total_tokens=int(
                    summary_data["total_tokens"]
                ),
                estimated_cost_usd=round(
                    float(
                        summary_data[
                            "estimated_cost_usd"
                        ]
                    ),
                    8,
                ),
                average_latency_ms=round(
                    float(
                        summary_data[
                            "average_latency_ms"
                        ]
                    ),
                    2,
                ),
            ),
            items=items,
            total=total,
            limit=limit,
            skip=skip,
        )

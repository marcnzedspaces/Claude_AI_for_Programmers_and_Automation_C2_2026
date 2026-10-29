from typing import Any

from pymongo import ASCENDING, DESCENDING

from app.schemas.usage import (
    AIOperation,
    AIUsageLog,
)


# Hide MongoDB's internal _id so only AIUsageLog fields come back.
USAGE_PROJECTION = {
    "_id": 0,
}


# The only code that talks to the ai_usage_logs collection.
# Services call these methods; they never write database queries themselves.
class UsageRepository:
    def __init__(self, database: Any) -> None:
        # MongoDB creates the collection the first time a document is inserted.
        self.collection = database.ai_usage_logs

    # Indexes make the filters used by list() and summarize() fast. Running this more than once is safe.
    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            "usage_id",
            # unique=True: MongoDB rejects a second log with the same usage_id.
            unique=True,
        )
        await self.collection.create_index(
            "request_id",
        )
        await self.collection.create_index(
            "ticket_id",
        )
        await self.collection.create_index(
            [
                # Compound index: speeds up "filter by operation, newest first".
                ("operation", ASCENDING),
                ("created_at", DESCENDING),
            ],
        )
        await self.collection.create_index(
            [
                ("created_at", DESCENDING),
            ],
        )

    # Stores one usage log. model_dump turns the Pydantic object into a plain dict for MongoDB.
    async def insert(
        self,
        usage: AIUsageLog,
    ) -> AIUsageLog:
        await self.collection.insert_one(
            usage.model_dump(mode="python")
        )
        return usage

    # Returns (one page of logs, total number of matching logs).
    # The * makes every filter keyword-only, so they cannot be mixed up.
    async def list(
        self,
        *,
        operation: AIOperation | None = None,
        model: str | None = None,
        request_id: str | None = None,
        ticket_id: str | None = None,
        limit: int = 20,
        skip: int = 0,
    ) -> tuple[list[AIUsageLog], int]:
        query = self._build_query(
            operation=operation,
            model=model,
            request_id=request_id,
            ticket_id=ticket_id,
        )

        # Count all matches first, so the client knows how many pages exist.
        total = await self.collection.count_documents(
            query
        )

        # Newest first; skip and limit then select the requested page.
        cursor = (
            self.collection.find(
                query,
                USAGE_PROJECTION,
            )
            .sort("created_at", DESCENDING)
            .skip(skip)
            .limit(limit)
        )

        items: list[AIUsageLog] = []

        # $group returns at most one document: the totals.
        async for document in cursor:
            items.append(
                AIUsageLog.model_validate(document)
            )

        return items, total

    # Totals for all logs that match the filters. MongoDB does the maths (an aggregation pipeline),
    # so we never load every log into Python.
    async def summarize(
        self,
        *,
        operation: AIOperation | None = None,
        model: str | None = None,
        request_id: str | None = None,
        ticket_id: str | None = None,
    ) -> dict[str, int | float]:
        query = self._build_query(
            operation=operation,
            model=model,
            request_id=request_id,
            ticket_id=ticket_id,
        )

        # A pipeline is a list of steps run inside MongoDB: $match filters the logs,
        # then $group adds them all up into one result.
        pipeline = [
            {
                "$match": query,
            },
            {
                "$group": {
                    "_id": None,
                    "total_calls": {
                        "$sum": 1,
                    },
                    "total_input_tokens": {
                        "$sum": "$input_tokens",
                    },
                    "total_output_tokens": {
                        "$sum": "$output_tokens",
                    },
                    "total_tokens": {
                        "$sum": "$total_tokens",
                    },
                    "estimated_cost_usd": {
                        "$sum": "$estimated_cost_usd",
                    },
                    "average_latency_ms": {
                        "$avg": "$latency_ms",
                    },
                }
            },
        ]

        cursor = await self.collection.aggregate(
            pipeline
        )

        # Validate every document from the database before the application uses it.
        async for document in cursor:
            # No logs matched the filters: return zeros instead of failing.
            return {
                "total_calls": int(
                    document.get(
                        "total_calls",
                        0,
                    )
                ),
                "total_input_tokens": int(
                    document.get(
                        "total_input_tokens",
                        0,
                    )
                ),
                "total_output_tokens": int(
                    document.get(
                        "total_output_tokens",
                        0,
                    )
                ),
                "total_tokens": int(
                    document.get(
                        "total_tokens",
                        0,
                    )
                ),
                "estimated_cost_usd": float(
                    document.get(
                        "estimated_cost_usd",
                        0.0,
                    )
                ),
                "average_latency_ms": float(
                    document.get(
                        "average_latency_ms",
                        0.0,
                    )
                ),
            }

        # int() and float() make sure plain Python numbers come back.
        return {
            "total_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "average_latency_ms": 0.0,
        }

    # Builds the MongoDB filter. Only filters the caller supplied are added,
    # so no filters at all means "match everything".
    @staticmethod
    def _build_query(
        *,
        operation: AIOperation | None,
        model: str | None,
        request_id: str | None,
        ticket_id: str | None,
    ) -> dict[str, object]:
        query: dict[str, object] = {}

        if operation is not None:
            # Query by the enum's text value, e.g. "faq_answer".
            query["operation"] = operation.value

        if model:
            query["model"] = model

        if request_id:
            query["request_id"] = request_id

        if ticket_id:
            query["ticket_id"] = ticket_id

        return query

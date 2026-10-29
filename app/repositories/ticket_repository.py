from typing import Any

from pymongo import ASCENDING, DESCENDING

from app.schemas.common import TicketCategory, TicketStatus
from app.schemas.ticket import TicketResponse


# Hide MongoDB's internal _id; everything else is the ticket shape.
TICKET_PROJECTION = {
    "_id": 0,
}


class TicketRepository:
    def __init__(self, database: Any) -> None:
        # Repositories own database access; routes and services do not.
        self.collection = database.tickets

    # Indexes make the lookups and filters below fast. Running this more than once is safe.
    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            "ticket_id",
            # unique=True: MongoDB rejects a second ticket with the same ticket_id.
            unique=True,
        )
        await self.collection.create_index(
            [("customer_id", ASCENDING), ("created_at", DESCENDING)],
        )
        await self.collection.create_index(
            [("status", ASCENDING), ("created_at", DESCENDING)],
        )
        await self.collection.create_index(
            [("analysis.category", ASCENDING), ("created_at", DESCENDING)],
        )

    async def insert(
        self,
        ticket: TicketResponse,
    ) -> TicketResponse:
        # The ticket was already validated by Pydantic; store it as a plain dict.
        document = ticket.model_dump(mode="python")
        await self.collection.insert_one(document)
        return ticket

    async def replace(
        self,
        ticket: TicketResponse,
    ) -> TicketResponse:
        document = ticket.model_dump(mode="python")

        # Replace the whole stored ticket that has the same ticket_id.
        result = await self.collection.replace_one(
            {
                "ticket_id": ticket.ticket_id,
            },
            document,
        )

        # matched_count is 0 when the ticket does not exist.
        if result.matched_count != 1:
            raise RuntimeError(
                f"Ticket {ticket.ticket_id} no longer exists."
            )

        return ticket

    async def get_by_id(
        self,
        ticket_id: str,
    ) -> TicketResponse | None:
        # Look the ticket up by its application-generated ticket_id.
        document = await self.collection.find_one(
            {
                "ticket_id": ticket_id,
            },
            TICKET_PROJECTION,
        )

        # No matching document means the ticket does not exist.
        if document is None:
            return None

        # Validate database data before the rest of the application uses it.
        return TicketResponse.model_validate(document)

    async def list(
        self,
        *,
        customer_id: str | None = None,
        status: TicketStatus | None = None,
        category: TicketCategory | None = None,
        limit: int = 20,
        skip: int = 0,
    ) -> tuple[list[TicketResponse], int]:
        # Build the filter from the optional arguments; no filters means all tickets.
        query: dict[str, object] = {}

        # Optional customer_id filter
        if customer_id:
            query["customer_id"] = customer_id

        # Compare by the enum's text value, e.g. "needs_human_review".
        if status is not None:
            query["status"] = status.value

        # The category lives inside the nested analysis object.
        if category is not None:
            query["analysis.category"] = category.value

        # Count all matches first, so the client knows how many pages exist.
        total = await self.collection.count_documents(query)

        # Newest tickets first, then apply pagination
        cursor = (
            self.collection.find(
                query,
                TICKET_PROJECTION,
            )
            .sort("created_at", DESCENDING)
            .skip(skip)
            .limit(limit)
        )

        items: list[TicketResponse] = []

        async for document in cursor:
            items.append(
                TicketResponse.model_validate(document)
            )

        return items, total

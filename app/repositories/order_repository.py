from typing import Any

from app.schemas.order import OrderContext


# Projection is an allowlist of fields the repository returns to the app.
ORDER_CONTEXT_PROJECTION = {
    "_id": 0,
    "order_id": 1,
    "status": 1,
    "items": 1,
    "estimated_delivery": 1,
    "delivered_at": 1,
}


class OrderRepository:
    def __init__(self, database: Any) -> None:
        # Repositories own database access; ClaudeService does not.
        self.collection = database.orders

    async def get_order_for_customer(
        self,
        customer_id: str,
        order_id: str,
    ) -> OrderContext | None:
        # Exercise 01: participants implement the customer-scoped query.
        # Scope the query to both the current customer and the requested order.
        document = await self.collection.find_one(
            {
                "customer_id": customer_id,
                "order_id": order_id,
            },
            ORDER_CONTEXT_PROJECTION,
        )

        # No matching customer/order pair means no authorized order is available.
        if document is None:
            return None

        # Validate database data before the rest of the application uses it.
        return OrderContext.model_validate(document)

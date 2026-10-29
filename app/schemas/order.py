from datetime import datetime
from enum import Enum

from pydantic import Field

from app.schemas.common import StrictModel


# Restrict order status to known application values.
class OrderStatus(str, Enum):
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    DELAYED = "delayed"
    CANCELLED = "cancelled"
    RETURNED = "returned"


# Only expose item fields needed for support responses.
class OrderItem(StrictModel):
    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(ge=1)


# This is the trusted subset of an order that may be passed to Claude.
class OrderContext(StrictModel):
    order_id: str = Field(min_length=3, max_length=50)
    status: OrderStatus
    items: list[OrderItem]
    estimated_delivery: datetime | None = None
    delivered_at: datetime | None = None

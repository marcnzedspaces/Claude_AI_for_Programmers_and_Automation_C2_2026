import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.repositories.faq_repository import FAQRepository
from app.repositories.order_repository import OrderRepository
from app.schemas.agent import (
    EscalateTicketArgs,
    GetOrderStatusArgs,
    SearchFAQArgs,
    ToolName,
)
from app.schemas.common import TicketStatus
from app.schemas.faq import FAQSource
from app.schemas.order import OrderContext
from app.schemas.ticket import TicketResponse
from app.services.ticket_service import TicketService


# What one tool call produces. Immutable (frozen) like the other result objects.
@dataclass(frozen=True)
class ToolExecutionResult:
    content: str
    is_error: bool
    summary: str
    order_context: OrderContext | None = None
    faq_context: list[FAQSource] | None = None


# A new registry is created for every request, so each tool is tied to one
# customer, one allowed order and one ticket. Claude cannot change any of these.
class ToolRegistry:
    def __init__(
        self,
        *,
        order_repository: OrderRepository,
        faq_repository: FAQRepository,
        ticket_service: TicketService,
        customer_id: str,
        allowed_order_id: str | None,
        ticket_id: str,
    ) -> None:
        # Bind tools to the current request/customer/ticket context.
        self.order_repository = order_repository
        self.faq_repository = faq_repository
        self.ticket_service = ticket_service
        self.customer_id = customer_id
        self.allowed_order_id = allowed_order_id
        self.ticket_id = ticket_id
        self._seen_calls: set[str] = set()

    def definitions(self) -> list[dict[str, Any]]:
        # These schemas describe the only capabilities Claude is told exist.
        # Each entry is name + description + input_schema. Claude reads the
        # description to decide when to use a tool, and the schema (generated
        # from the Args models) to know which arguments to send.
        return [
            {
                "name": ToolName.GET_ORDER_STATUS.value,
                "description": (
                    "Retrieve safe status information for the order ID "
                    "supplied with the current support request. Use this "
                    "when the customer asks where their order is, whether "
                    "it was delivered, or when it is expected. The "
                    "application independently binds the lookup to the "
                    "current customer and only permits the request's order "
                    "ID, so this tool cannot be used to browse other "
                    "customers or arbitrary order IDs. A successful tool "
                    "call may still return found=false when the order "
                    "cannot be verified for the current customer."
                ),
                "input_schema": (
                    GetOrderStatusArgs.model_json_schema()
                ),
            },
            {
                "name": ToolName.SEARCH_FAQ.value,
                "description": (
                    "Search the application's approved FAQ knowledge for "
                    "support policy or general guidance. Use this before "
                    "stating return, billing, delivery-policy, account, "
                    "or other FAQ facts. The tool is read-only and "
                    "returns at most three approved FAQ records. It does "
                    "not provide private order data and it does not "
                    "perform business actions."
                ),
                "input_schema": SearchFAQArgs.model_json_schema(),
            },
            {
                "name": ToolName.ESCALATE_TICKET.value,
                "description": (
                    "Escalate the current support ticket for human "
                    "handling with a concise reason. Use this for issues "
                    "that warrant human attention, such as repeated "
                    "failures, urgent concerns, or situations that cannot "
                    "be resolved safely with available information. The "
                    "application binds this action to the current ticket; "
                    "you cannot choose another ticket. This tool does not "
                    "issue refunds, payments, cancellations, or other "
                    "financial/account actions."
                ),
                "input_schema": (
                    EscalateTicketArgs.model_json_schema()
                ),
            },
        ]

    # Entry point used by the agent loop for every tool_use block. raw_input is
    # exactly what Claude sent, so it is untrusted until a tool validates it.
    # The result always comes back as a ToolExecutionResult, never an exception,
    # so one bad tool call does not crash the whole request.
    async def execute(
        self,
        tool_name: str,
        raw_input: Any,
    ) -> ToolExecutionResult:
        allowed_names = {
            item.value
            for item in ToolName
        }

        if tool_name not in allowed_names:
            return ToolExecutionResult(
                content=json.dumps(
                    {
                        "error": "Tool is not allowlisted.",
                    }
                ),
                is_error=True,
                summary=(
                    "Blocked non-allowlisted tool request."
                ),
            )

        fingerprint = json.dumps(
            {
                "tool_name": tool_name,
                "input": raw_input,
            },
            sort_keys=True,
            default=str,
        )

        if fingerprint in self._seen_calls:
            return ToolExecutionResult(
                content=json.dumps(
                    {
                        "error": (
                            "Duplicate tool request blocked."
                        )
                    }
                ),
                is_error=True,
                summary="Blocked duplicate tool request.",
            )

        self._seen_calls.add(fingerprint)

        if tool_name == ToolName.GET_ORDER_STATUS.value:
            return await self._get_order_status(raw_input)

        if tool_name == ToolName.SEARCH_FAQ.value:
            return await self._search_faq(raw_input)

        return await self._escalate_ticket(raw_input)

    # Tool: get_order_status. Three checks run in this order: valid arguments,
    # an order ID exists on the request, and it matches that ID. Only then
    # does the repository query the database.
    async def _get_order_status(
        self,
        raw_input: Any,
    ) -> ToolExecutionResult:
        try:
            args = GetOrderStatusArgs.model_validate(
                raw_input
            )
        except ValidationError:
            return self._invalid_arguments(
                ToolName.GET_ORDER_STATUS
            )

        # No order on the current request means no order lookup authority.
        if self.allowed_order_id is None:
            return ToolExecutionResult(
                content=json.dumps(
                    {
                        "error": (
                            "No order ID was supplied with "
                            "the current request."
                        )
                    }
                ),
                is_error=True,
                summary=(
                    "Blocked order lookup because the request "
                    "contains no order ID."
                ),
            )

        if args.order_id != self.allowed_order_id:
            return ToolExecutionResult(
                content=json.dumps(
                    {
                        "error": (
                            "That order ID is not permitted "
                            "for this request."
                        )
                    }
                ),
                is_error=True,
                summary=(
                    "Blocked attempt to switch to a different "
                    "order ID."
                ),
            )

        # Repository adds the customer scope as the final data-access boundary.
        order = (
            await self.order_repository.get_order_for_customer(
                self.customer_id,
                args.order_id,
            )
        )

        # Not found is a normal answer, not an error. The same result is
        # returned if the order exists but belongs to another customer, so
        # Claude learns nothing about orders the customer cannot see.
        if order is None:
            return ToolExecutionResult(
                content=json.dumps(
                    {
                        "found": False,
                        "message": (
                            "No order could be verified for the "
                            "current customer and supplied order ID."
                        ),
                    }
                ),
                is_error=False,
                summary="No authorized order was found.",
            )

        return ToolExecutionResult(
            content=json.dumps(
                {
                    "found": True,
                    "order": order.model_dump(
                        mode="json"
                    ),
                }
            ),
            is_error=False,
            summary=(
                f"Verified order {order.order_id} "
                f"with status {order.status.value}."
            ),
            order_context=order,
        )

    # Tool: search_faq. Claude chooses the query text, but the search itself
    # is a normal repository call that only returns approved FAQ records.
    async def _search_faq(
        self,
        raw_input: Any,
    ) -> ToolExecutionResult:
        try:
            args = SearchFAQArgs.model_validate(
                raw_input
            )
        except ValidationError:
            return self._invalid_arguments(
                ToolName.SEARCH_FAQ
            )

        results = await self.faq_repository.search(
            args.query,
            limit=3,
        )

        return ToolExecutionResult(
            content=json.dumps(
                {
                    "matches": [
                        item.model_dump(mode="json")
                        for item in results
                    ]
                }
            ),
            is_error=False,
            summary=(
                f"FAQ search returned {len(results)} "
                "approved record(s)."
            ),
            faq_context=results,
        )

    # Tool: escalate_ticket. The only tool that changes saved data. It marks
    # the current ticket as ESCALATED with Claude's reason, and nothing else.
    async def _escalate_ticket(
        self,
        raw_input: Any,
    ) -> ToolExecutionResult:
        try:
            args = EscalateTicketArgs.model_validate(
                raw_input
            )
        except ValidationError:
            return self._invalid_arguments(
                ToolName.ESCALATE_TICKET
            )

        ticket = await self.ticket_service.get(
            self.ticket_id
        )

        if ticket is None:
            return ToolExecutionResult(
                content=json.dumps(
                    {
                        "error": "Current ticket was not found.",
                    }
                ),
                is_error=True,
                summary="Escalation failed: ticket missing.",
            )

        if ticket.status == TicketStatus.CLOSED:
            return ToolExecutionResult(
                content=json.dumps(
                    {
                        "error": (
                            "Closed tickets cannot be escalated."
                        )
                    }
                ),
                is_error=True,
                summary="Escalation blocked for closed ticket.",
            )

        updated = TicketResponse.model_validate(
            {
                **ticket.model_dump(mode="python"),
                "status": TicketStatus.ESCALATED,
                "escalation_reason": args.reason,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        await self.ticket_service.save(updated)

        return ToolExecutionResult(
            content=json.dumps(
                {
                    "success": True,
                    "ticket_id": ticket.ticket_id,
                    "status": TicketStatus.ESCALATED.value,
                }
            ),
            is_error=False,
            summary="Current ticket escalated for human review.",
        )

    # Shared error result for all three tools. The message is deliberately
    # generic: it does not echo back the invalid input or the Pydantic details.
    @staticmethod
    def _invalid_arguments(
        tool_name: ToolName,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            content=json.dumps(
                {
                    "error": (
                        "Tool arguments failed application "
                        "validation."
                    )
                }
            ),
            is_error=True,
            summary=(
                f"Invalid arguments blocked for "
                f"{tool_name.value}."
            ),
        )

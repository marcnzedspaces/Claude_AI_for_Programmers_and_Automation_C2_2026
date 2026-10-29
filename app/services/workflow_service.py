from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter

from app.repositories.faq_repository import FAQRepository
from app.repositories.order_repository import OrderRepository
from app.schemas.common import Priority, TicketStatus
from app.schemas.ticket import (
    TicketCreateRequest,
    TicketResponse,
)
from app.schemas.usage import AIUsage
from app.schemas.workflow import (
    ProcessTicketRequest,
    WorkflowStep,
)
from app.services.analysis_service import AnalysisService
from app.services.response_service import ResponseService
from app.services.ticket_service import TicketService


# What the workflow hands back to the route. Immutable (frozen) so the result
# cannot be changed by accident after the workflow has finished.
@dataclass(frozen=True)
class WorkflowProcessResult:
    ticket: TicketResponse
    executed_steps: list[WorkflowStep]
    analysis_usage: AIUsage
    response_usage: AIUsage


# Orchestrates existing services and repositories into one use case. It
# contains no new capability of its own, only the sequence and the rules.
class WorkflowService:
    def __init__(
        self,
        *,
        analysis_service: AnalysisService,
        response_service: ResponseService,
        ticket_service: TicketService,
        order_repository: OrderRepository,
        faq_repository: FAQRepository,
    ) -> None:
        # The workflow owns orchestration across existing capabilities.
        # Everything is passed in (not created here), so the route controls
        # the lifecycle and tests can swap in fakes.
        self.analysis_service = analysis_service
        self.response_service = response_service
        self.ticket_service = ticket_service
        self.order_repository = order_repository
        self.faq_repository = faq_repository

    async def process(
        self,
        request: ProcessTicketRequest,
    ) -> WorkflowProcessResult:
        # Records each step as it runs. The response reports this list, so a
        # skipped step (for example no order lookup) is visible to the caller.
        steps: list[WorkflowStep] = []

        analysis_started = perf_counter()
        analysis_result = await self.analysis_service.analyse(
            request.message
        )
        analysis_latency_ms = int(
            (perf_counter() - analysis_started) * 1000
        )
        steps.append(WorkflowStep.ANALYSIS)

        # .data is the TicketAnalysis, already validated by Pydantic.
        analysis = analysis_result.data
        # Trusted context starts empty and is filled only by real lookups.
        order_context = None
        faq_context = []

        # Python owns the initial human-review business rule. Claude can ask
        # for a review, but an urgent ticket always gets one regardless.
        requires_human_review = (
            analysis.needs_human_review
            or analysis.priority == Priority.URGENT
        )

        # Step 2a: retrieve order data only when analysis says it is needed.
        if analysis.needs_order_lookup:
            if request.order_id:
                # The repository filters on customer_id AND order_id, so a
                # customer can never read someone else's order. It returns
                # None when no authorised order matches.
                order_context = (
                    await self.order_repository.get_order_for_customer(
                        request.customer_id,
                        request.order_id,
                    )
                )
                steps.append(WorkflowStep.ORDER_LOOKUP)

            # Missing required trusted order context forces human review.
            if order_context is None:
                requires_human_review = True

        # Step 2b: retrieve approved FAQ evidence when needed.
        if analysis.needs_faq_lookup:
            faq_context = await self.faq_repository.search(
                analysis.faq_query or request.message,
                limit=3,
            )
            steps.append(WorkflowStep.FAQ_LOOKUP)

            # Do not invent policy when approved evidence is unavailable.
            if not faq_context:
                requires_human_review = True

        ticket = await self.ticket_service.create(
            TicketCreateRequest(
                customer_id=request.customer_id,
                order_id=request.order_id,
                message=request.message,
            ),
            analysis,
        )
        steps.append(WorkflowStep.DATABASE_INSERT)

        response_started = perf_counter()
        # Step 4: Claude drafts using only retrieved trusted context.
        # If order_context or faq_context is empty, the draft cannot cite
        # those facts, and requires_human_review is already True above.
        response_result = (
            await self.response_service.generate_draft(
                request.message,
                order_context=order_context,
                faq_context=faq_context,
            )
        )
        response_latency_ms = int(
            (perf_counter() - response_started) * 1000
        )
        steps.append(WorkflowStep.RESPONSE_GENERATION)

        # Step 5: Python determines the final business status.
        final_status = (
            TicketStatus.NEEDS_HUMAN_REVIEW
            if requires_human_review
            else TicketStatus.PROCESSED
        )

        updated_ticket = TicketResponse.model_validate(
            {
                **ticket.model_dump(mode="python"),
                "order_context": order_context,
                "faq_context": faq_context,
                "draft_response": response_result.text,
                "status": final_status,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        updated_ticket = await self.ticket_service.save(
            updated_ticket
        )
        steps.append(WorkflowStep.DATABASE_UPDATE)

        # Keep analysis and response usage separate for observability.
        return WorkflowProcessResult(
            ticket=updated_ticket,
            executed_steps=steps,
            analysis_usage=AIUsage(
                model=analysis_result.model,
                input_tokens=analysis_result.input_tokens,
                output_tokens=analysis_result.output_tokens,
                latency_ms=analysis_latency_ms,
            ),
            response_usage=AIUsage(
                model=response_result.model,
                input_tokens=response_result.input_tokens,
                output_tokens=response_result.output_tokens,
                latency_ms=response_latency_ms,
            ),
        )

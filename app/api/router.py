from fastapi import APIRouter

from app.api.routes.agent import router as agent_router
from app.api.routes.ai import router as ai_router
from app.api.routes.faq import router as faq_router
from app.api.routes.health import router as health_router
from app.api.routes.tickets import router as tickets_router
from app.api.routes.usage import router as usage_router
from app.api.routes.workflows import router as workflows_router


# main.py -> api_router -> one router per feature (app/api/routes/*.py)
# This file is the single place where every route module is plugged into the
# application. A new routes file does nothing until it is included here.
api_router = APIRouter()
# Day 1: health check and the basic AI endpoints (/summarise, /analyse, ...)
api_router.include_router(health_router)
api_router.include_router(ai_router)
# Day 2: ticket storage and FAQ retrieval
api_router.include_router(tickets_router)
api_router.include_router(faq_router)
# Day 2: the same capabilities combined in two different ways.
# /workflows/process-ticket -> Python decides every step (deterministic).
# /agent/support            -> Claude chooses which tools to call (agentic).
api_router.include_router(workflows_router)
# Attach /agent endpoints to the API.
api_router.include_router(agent_router)
# AI usage logs and their summary.
api_router.include_router(usage_router)

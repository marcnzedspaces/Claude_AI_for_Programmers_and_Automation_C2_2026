from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from app.config import get_settings


# Claude -> structured response parsing -> Pydantic validation -> application data
class ClaudeConfigurationError(RuntimeError):
    # Raised when a required setting (API key, model) is missing or empty,
    # so callers can tell a setup problem apart from an API failure.
    pass


class ClaudeResponseError(RuntimeError):
    # Raised when Claude's reply is unusable (it did not match the expected
    # schema, or it was empty), so callers can tell it apart from a setup problem.
    pass


# Plain-text reply plus the usage numbers the application records.
@dataclass(frozen=True)
class ClaudeTextResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


# Stands for "any Pydantic model", so generate_structured can return whichever
# model the caller asks for while keeping type hints accurate.
StructuredModel = TypeVar(
    "StructuredModel",
    bound=BaseModel,
)


# A reply already parsed and validated into a Pydantic model, plus usage numbers.
@dataclass(frozen=True)
class ClaudeStructuredResult(Generic[StructuredModel]):
    data: StructuredModel
    model: str
    input_tokens: int
    output_tokens: int


class ClaudeService:
    # Low-level wrapper around the Anthropic Messages API.

    def __init__(self) -> None:
        # Read settings (loaded from environment / .env) once at construction.
        settings = get_settings()

        # Fail early with a clear message if the key was never provided.
        if settings.anthropic_api_key is None:
            raise ClaudeConfigurationError(
                "ANTHROPIC_API_KEY is not configured."
            )

        api_key = settings.anthropic_api_key.get_secret_value().strip()
        # A key that is only whitespace passes the None check above, so
        # guard against it separately.
        if not api_key:
            raise ClaudeConfigurationError(
                "ANTHROPIC_API_KEY is empty."
            )

        if not settings.claude_model:
            raise ClaudeConfigurationError(
                "CLAUDE_MODEL is not configured."
            )

        self.model = settings.claude_model
        # Async client so FastAPI's event loop is not blocked while waiting
        # for Claude. Timeout and retry behaviour come from settings.
        self.client = AsyncAnthropic(
            api_key=api_key,
            timeout=settings.claude_timeout_seconds,
            max_retries=settings.claude_max_retries,
        )

    async def generate_text(
        self,
        user_message: str,
        *,
        max_tokens: int = 300,
        system: str | None = None,
    ) -> ClaudeTextResult:
        # Ask Claude for free text. The request is a dict so the optional
        # system prompt can be added below.
        request = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": user_message,
                }
            ],
        }

        if system:
            request["system"] = system

        # One call to the Anthropic Messages API.
        message = await self.client.messages.create(**request)

        # message.content is a list of blocks (text, tool use, etc.).
        # Keep only the text blocks, then join them into a single string.
        text_parts = [
            block.text
            for block in message.content
            if block.type == "text"
        ]
        text = "\n".join(text_parts).strip()

        # Return only the fields the rest of the app needs.
        return ClaudeTextResult(
            text=text,
            model=message.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )

    async def generate_structured(
        self,
        user_message: str,
        *,
        output_model: type[StructuredModel],
        max_tokens: int = 500,
        system: str | None = None,
    ) -> ClaudeStructuredResult[StructuredModel]:
        # Same request shape as generate_text, plus output_format, which
        # tells the SDK which schema to request and parse the reply into.
        request = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": user_message,
                }
            ],
            "output_format": output_model,
        }

        # Add optional request fields only when the caller supplies them.
        if system:
            request["system"] = system

        try:
            message = await self.client.messages.parse(**request)
        except ValidationError as exc:
            # The reply did not pass the schema: raise our own error type.
            raise ClaudeResponseError(
                "Claude structured output failed application validation."
            ) from exc

        # parsed_output is None when nothing could be parsed (for example,
        # the response was cut off or refused), so check before using it.
        if message.parsed_output is None:
            # The reply did not match the schema: never treat it as valid
            # application data. Re-raise as our own error type.
            raise ClaudeResponseError(
                "Claude returned no parsed structured output."
            )

        return ClaudeStructuredResult(
            data=message.parsed_output,
            model=message.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )

    # Lower-level call used by the agent loop: the caller passes the whole
    # conversation (and the tools Claude may request) and gets the raw reply back.
    async def create_message(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 600,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        # Only include "system" when one was given; the API does not want
        # an empty or None value for it.
        if system:
            request["system"] = system

        if tools:
            request["tools"] = tools

        return await self.client.messages.create(**request)

    async def close(self) -> None:
        # Releases the HTTP connections held by the client. Meant to be
        # called once when the application shuts down.
        await self.client.close()

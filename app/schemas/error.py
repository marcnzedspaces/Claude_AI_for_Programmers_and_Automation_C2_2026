from pydantic import Field

from app.schemas.common import StrictModel


# One invalid field in a request (listed inside a 422 error).
class ValidationIssue(StrictModel):
    location: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=500)
    error_type: str = Field(min_length=1, max_length=100)


# The body of every error: a stable code, a safe message and the request ID.
class ErrorDetail(StrictModel):
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    request_id: str = Field(min_length=1, max_length=100)
    details: list[ValidationIssue] = Field(
        default_factory=list,
    )


# Every error reply is {"error": {...}}, so clients handle errors in one way.
class ErrorResponse(StrictModel):
    error: ErrorDetail

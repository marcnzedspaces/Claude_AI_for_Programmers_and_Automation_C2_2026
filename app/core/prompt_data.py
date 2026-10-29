import json
from typing import Any


# Used wherever trusted application data and untrusted customer text share one prompt.
def serialize_prompt_payload(
    payload: dict[str, Any],
) -> str:
    """
    Serialize application data for inclusion in a prompt.

    JSON encoding preserves untrusted text as a string value instead of
    allowing delimiter-like text to become application-created structure.
    """
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    )

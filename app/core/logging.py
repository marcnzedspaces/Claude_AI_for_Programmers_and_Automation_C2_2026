import json
import logging
from typing import Any


# All application logs go through one named logger, so they are easy to find and filter.
LOGGER_NAME = "supportops"
logger = logging.getLogger(LOGGER_NAME)


# Called once at startup (see main.py). Sets the log level and the text format of each line.
def configure_logging(level: str) -> None:
    level_value = getattr(
        logging,
        level.upper(),
        logging.INFO,
    )

    logger.setLevel(level_value)

    # Only add a handler once; otherwise every reload would print each line twice.
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(message)s")
        )
        logger.addHandler(handler)

    # Stop messages bubbling up to the root logger, which would print them a second time.
    logger.propagate = False


# Writes one structured log line: an event name plus extra fields, as JSON.
# JSON is easy to search. Only pass safe fields: never log secrets or full customer messages.
def log_event(
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    payload = {
        "event": event,
        **fields,
    }

    logger.log(
        level,
        json.dumps(
            payload,
            ensure_ascii=False,
            # default=str lets values such as datetimes and enums be logged without errors.
            default=str,
            sort_keys=True,
        ),
    )

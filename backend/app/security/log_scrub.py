"""Logging filter that masks PII before anything reaches a log sink."""
import logging

from .pii import mask


class PiiScrubber(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        record.msg, record.args = mask(msg)[0], ()
        return True


def install() -> None:
    for name in ("", "uvicorn", "uvicorn.access", "uvicorn.error", "finsight"):
        logging.getLogger(name).addFilter(PiiScrubber())

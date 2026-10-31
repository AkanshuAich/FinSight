"""The only route to an external model (Jev, Claude). Masks, re-scans, blocks, logs.

A payload that still contains detectable PII after masking is blocked, not sent with a warning.
If the deployment does not allow external models (FINSIGHT_EXTERNAL_MODELS != "1"), nothing leaves.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

from ..db import connect
from .pii import residual_pii


class EgressBlocked(Exception):
    pass


def external_allowed() -> bool:
    return os.environ.get("FINSIGHT_EXTERNAL_MODELS", "0") == "1"


def send(target: str, payload: dict, transport) -> dict:
    """`payload` must already hold placeholder-masked text. `transport(payload) -> dict` does the call."""
    body = json.dumps(payload, sort_keys=True)
    found = residual_pii(body)
    blocked = bool(found) or not external_allowed()
    reason = f"residual PII: {sorted(set(found))}" if found else ("external models disabled for this deployment" if blocked else "")
    connect().execute("INSERT INTO security.egress_log VALUES (?, ?, ?, ?, ?, ?)",
                      [uuid.uuid4().hex, datetime.utcnow(), target, body[:4000], blocked, reason])
    if blocked:
        raise EgressBlocked(reason)
    return transport(payload)

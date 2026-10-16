"""Wire validation and canonical proposal data."""

from __future__ import annotations

import hashlib
import json
import uuid


MESSAGE_TYPES = {"REQUEST", "FILTER", "REQUIREMENTS", "FACTS", "PROPOSAL", "ACCEPT", "REJECT", "APPROVAL"}
TERMINAL_STATES = {"NO_MATCH", "REJECTED", "CONNECTED"}


def new_id() -> str:
    return uuid.uuid4().hex


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def proposal_digest(scenario_id: str, requester_id: str, provider_id: str, terms: dict, version: int = 1) -> str:
    material = {"scenario_id": scenario_id, "requester_id": requester_id, "provider_id": provider_id, "terms": terms, "version": version}
    return hashlib.sha256(canonical_json(material).encode()).hexdigest()


def validate_envelope(value: dict) -> dict:
    required = {"schema_version", "message_id", "request_id", "session_id", "sender_agent_id", "recipient_agent_id", "type", "causation_id", "payload"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("message envelope has invalid keys")
    if value["schema_version"] != 1 or value["type"] not in MESSAGE_TYPES:
        raise ValueError("unsupported message schema or type")
    for field in ("message_id", "request_id", "session_id", "sender_agent_id", "recipient_agent_id"):
        if not isinstance(value[field], str) or not value[field]:
            raise ValueError(f"message {field} is required")
    if value["causation_id"] is not None and not isinstance(value["causation_id"], str):
        raise ValueError("invalid causation_id")
    if not isinstance(value["payload"], dict):
        raise ValueError("message payload must be object")
    return value

"""
Ecosystem Internal Language (EIL) v1.0

The universal communication protocol for the Decentralized AI Ecosystem.
Every agent, service, and component communicates using this language.

Protocol Format (JSON):
{
  "src": "agent_name",       # SOURCE: who sent this
  "dst": "agent_name|*",    # TARGET: who should receive (* = broadcast)
  "type": "msg_type",       # TYPE: see MSG_TYPES below
  "task": "description",    # TASK: what needs to be done
  "priority": 0-10,         # PRIORITY: 0=lowest, 10=critical
  "status": "state",        # STATUS: pending|active|done|failed|idle
  "result": {},             # RESULT: output payload
  "id": "uuid",             # ID: unique message identifier
  "ref": "uuid",            # REF: references a previous message (reply chain)
  "tick": 0,                # TICK: ecosystem tick count
  "sender_type": "type",    # SENDER_TYPE: agent category
}

Message Types (MSG_TYPES):
  - request    : Ask another agent to do something
  - response   : Reply to a request
  - broadcast  : Message to all agents
  - task       : Task assignment
  - result     : Task result delivery
  - status     : Status update / heartbeat
  - query      : Request information
  - info       : Information delivery
  - error      : Error report
  - discover   : Agent discovery announcement
  - register   : Agent registration
  - learn      : Knowledge sharing
  - evolve     : Evolution suggestion
  - health     : Health check / heartbeat
"""

import json
import time
import uuid
from typing import Any, Dict, Optional
from dataclasses import dataclass, field, asdict


MSG_TYPES = {
    "request", "response", "broadcast", "task", "result",
    "status", "query", "info", "error", "discover",
    "register", "learn", "evolve", "health",
}

PRIORITIES = {
    "lowest": 0, "low": 2, "normal": 5, "high": 8, "critical": 10,
}

STATUSES = {"pending", "active", "done", "failed", "idle", "unknown"}


@dataclass
class EILMessage:
    src: str
    dst: str = "*"
    type: str = "info"
    task: str = ""
    priority: int = 5
    status: str = "unknown"
    result: Dict[str, Any] = field(default_factory=dict)
    id: str = ""
    ref: str = ""
    tick: int = 0
    sender_type: str = "agent"
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.id:
            self.id = f"{self.src}-{uuid.uuid4().hex[:12]}"
        if self.type not in MSG_TYPES:
            self.type = "info"

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v != "" and v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EILMessage":
        valid_keys = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    @classmethod
    def from_json(cls, raw: str) -> "EILMessage":
        return cls.from_dict(json.loads(raw))

    @classmethod
    def request(cls, src: str, dst: str, task: str, priority: int = 5,
                result: Optional[Dict] = None, sender_type: str = "agent") -> "EILMessage":
        return cls(src=src, dst=dst, type="request", task=task,
                   priority=priority, status="pending",
                   result=result or {}, sender_type=sender_type)

    @classmethod
    def response(cls, src: str, dst: str, ref: str, result: Dict[str, Any],
                 status: str = "done", task: str = "") -> "EILMessage":
        return cls(src=src, dst=dst, type="response", task=task,
                   status=status, result=result, ref=ref)

    @classmethod
    def broadcast(cls, src: str, task: str, result: Optional[Dict] = None,
                  sender_type: str = "agent") -> "EILMessage":
        return cls(src=src, dst="*", type="broadcast", task=task,
                   result=result or {}, sender_type=sender_type)

    @classmethod
    def task(cls, src: str, dst: str, task: str, priority: int = 5,
             result: Optional[Dict] = None) -> "EILMessage":
        return cls(src=src, dst=dst, type="task", task=task,
                   priority=priority, status="pending",
                   result=result or {}, sender_type="coordinator")

    @classmethod
    def status_report(cls, src: str, status: str, result: Dict[str, Any],
                      sender_type: str = "agent") -> "EILMessage":
        return cls(src=src, dst="*", type="status", status=status,
                   result=result, sender_type=sender_type)

    @classmethod
    def error(cls, src: str, dst: str, task: str, error_detail: str,
              ref: str = "") -> "EILMessage":
        return cls(src=src, dst=dst, type="error", task=task,
                   status="failed", result={"error": error_detail},
                   ref=ref)

    @classmethod
    def learn(cls, src: str, knowledge: Dict[str, Any],
              dst: str = "memory") -> "EILMessage":
        return cls(src=src, dst=dst, type="learn", task="share_knowledge",
                   result=knowledge, sender_type="agent")

    @classmethod
    def register_agent(cls, src: str, sender_type: str,
                       capabilities: Dict[str, Any]) -> "EILMessage":
        return cls(src=src, dst="kernel", type="register",
                   task="agent_registration", result=capabilities,
                   sender_type=sender_type)

    @classmethod
    def health(cls, src: str, result: Dict[str, Any]) -> "EILMessage":
        return cls(src=src, dst="monitor", type="health",
                   task="heartbeat", result=result,
                   sender_type="agent")


from dataclasses import fields


def format_eil(msg: EILMessage) -> str:
    """Human-readable EIL format for logging/debug."""
    parts = [
        f"SOURCE: {msg.src}",
        f"TARGET: {msg.dst}",
        f"TYPE: {msg.type}",
        f"TASK: {msg.task}",
        f"PRIORITY: {msg.priority}",
        f"STATUS: {msg.status}",
    ]
    if msg.result:
        parts.append(f"RESULT: {json.dumps(msg.result, default=str)[:200]}")
    return "\n".join(parts)


def parse_eil(raw: str) -> Optional[EILMessage]:
    """Parse a raw JSON string into an EILMessage."""
    try:
        return EILMessage.from_json(raw)
    except (json.JSONDecodeError, TypeError, KeyError):
        return None

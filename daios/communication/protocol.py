"""DAIOS Internal Communication Protocol — compact, human-readable message format.

Message types:
  - request:  Agent requests action/info from another agent or kernel
  - response: Reply to a request
  - broadcast: Message to all agents
  - observe:   Agent reports an observation to memory
  - learn:     Agent shares a learned pattern
  - propose:   Agent proposes a hypothesis/discovery
  - task:      Task assignment
  - status:    Status update
  - error:     Error report
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass, field, asdict
import time
import json


@dataclass
class DAIOSMessage:
    msg_type: str
    from_id: str
    to_id: str
    content: Dict[str, Any]
    msg_id: str = ""
    in_response_to: str = ""
    tick: int = 0
    priority: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        return cls(**data)

    @classmethod
    def request(cls, from_id: str, to_id: str, command: str, params: Optional[Dict] = None,
                msg_id: str = "") -> "DAIOSMessage":
        return cls(
            msg_type="request",
            from_id=from_id,
            to_id=to_id,
            content={"command": command, "params": params or {}},
            msg_id=msg_id or f"{from_id}-{int(time.time()*1000)}",
        )

    @classmethod
    def response(cls, from_id: str, to_id: str, data: Any, in_response_to: str = "") -> "DAIOSMessage":
        return cls(
            msg_type="response",
            from_id=from_id,
            to_id=to_id,
            content={"data": data},
            in_response_to=in_response_to,
            msg_id=f"resp-{from_id}-{int(time.time()*1000)}",
        )

    @classmethod
    def broadcast(cls, from_id: str, content: Dict[str, Any], msg_type: str = "broadcast") -> "DAIOSMessage":
        return cls(
            msg_type=msg_type,
            from_id=from_id,
            to_id="*",
            content=content,
            msg_id=f"bcast-{from_id}-{int(time.time()*1000)}",
        )

    @classmethod
    def observe(cls, from_id: str, observation: Dict[str, Any]) -> "DAIOSMessage":
        return cls(
            msg_type="observe",
            from_id=from_id,
            to_id="memory",
            content=observation,
            msg_id=f"obs-{from_id}-{int(time.time()*1000)}",
        )

    @classmethod
    def learn(cls, from_id: str, pattern: Dict[str, Any]) -> "DAIOSMessage":
        return cls(
            msg_type="learn",
            from_id=from_id,
            to_id="memory",
            content=pattern,
            msg_id=f"learn-{from_id}-{int(time.time()*1000)}",
        )

    @classmethod
    def propose(cls, from_id: str, hypothesis: Dict[str, Any]) -> "DAIOSMessage":
        return cls(
            msg_type="propose",
            from_id=from_id,
            to_id="kernel",
            content=hypothesis,
            msg_id=f"prop-{from_id}-{int(time.time()*1000)}",
        )


COMPACT_FORMAT = {
    "t": "msg_type",
    "f": "from_id",
    "to": "to_id",
    "c": "content",
    "id": "msg_id",
    "r": "in_response_to",
    "tk": "tick",
    "p": "priority",
}


def compact_encode(msg: DAIOSMessage) -> str:
    d = msg.to_dict()
    out = {}
    for short, long in COMPACT_FORMAT.items():
        if long in d and d[long]:
            out[short] = d[long]
    return json.dumps(out, separators=(",", ":"))


def compact_decode(data: str) -> DAIOSMessage:
    d = json.loads(data)
    expanded = {}
    for short, long in COMPACT_FORMAT.items():
        if short in d:
            expanded[long] = d[short]
    return DAIOSMessage.from_dict(expanded)

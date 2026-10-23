"""Server-controlled opt-in experiments; defaults preserve packet decisions."""
from dataclasses import dataclass
import json,os
@dataclass(frozen=True)
class GuardConfig:
    active_agent_mode: str = "client"
    proposal_mode: str = "packet"
    routing_mode: str = "runtime"
    digest_check: bool = True
    publication_protocol: str = "packet"
    generation_precheck: bool = False
    commit_variant: str = "full"
    def __post_init__(self):
        for name,allowed in {
            "active_agent_mode":{"client","server_strict"},
            "proposal_mode":{"packet","abort","drop_log"},
            "routing_mode":{"runtime","firstmatch","reach_only","table"},
            "publication_protocol":{"packet","cooperative"},
            "commit_variant":{"full","none","digest_only","slice","slice_prompt"},
        }.items():
            if getattr(self,name) not in allowed:raise ValueError(f"Invalid guard setting {name}.")
    @classmethod
    def from_environment(cls):
        return cls(**json.loads(os.environ.get("ROOM_GUARD_CONFIG","{}")))

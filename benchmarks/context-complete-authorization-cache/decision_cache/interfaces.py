from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class PolicySnapshot:
    revision: int
    evaluation_token: object

class PolicyStoreProtocol(Protocol):
    def snapshot(self,tenant_id:str,subject_id:str)->PolicySnapshot: ...
    def evaluate(self,snapshot:PolicySnapshot,resource_id:str,action:str)->bool: ...

class ClockProtocol(Protocol):
    def now(self)->int: ...

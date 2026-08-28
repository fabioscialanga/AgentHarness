from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class StoreError(Exception):
    """Controlled durable-store failure."""


@dataclass(frozen=True)
class Channel:
    channel_id: str
    artifact_digest: str
    generation: int


@dataclass(frozen=True)
class PublicationEvent:
    request_id: str
    channel_id: str
    previous_digest: str
    artifact_digest: str
    generation: int


@dataclass(frozen=True)
class Receipt:
    request_id: str
    command_fingerprint: str
    status_code: int
    response_body: bytes


class ReleaseStore(Protocol):
    def begin(self) -> object: ...
    def find_receipt(self, tx: object, request_id: str) -> Receipt | None: ...
    def read_channel(self, tx: object, channel_id: str) -> Channel | None: ...
    def artifact_is_approved(self, tx: object, artifact_digest: str) -> bool: ...
    def stage_channel(self, tx: object, channel: Channel) -> None: ...
    def stage_event(self, tx: object, event: PublicationEvent) -> None: ...
    def stage_receipt(self, tx: object, receipt: Receipt) -> None: ...
    def list_events(self, tx: object, channel_id: str) -> list[PublicationEvent]: ...
    def commit(self, tx: object) -> None: ...
    def rollback(self, tx: object) -> None: ...

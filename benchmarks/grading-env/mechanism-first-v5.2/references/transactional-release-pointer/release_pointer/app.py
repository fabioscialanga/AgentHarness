from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .interfaces import Channel, PublicationEvent, Receipt, StoreError

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
MAX = 9223372036854775807



def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _error(code: str, status: int) -> JSONResponse:
    return JSONResponse({"detail": code}, status_code=status)


def _fingerprint(channel_id: str, body: dict[str, Any]) -> str:
    canonical = {
        "artifact_digest": body["artifact_digest"],
        "channel_id": channel_id,
        "expected_generation": body["expected_generation"],
        "request_id": body["request_id"],
    }
    return hashlib.sha256(_json_bytes(canonical)).hexdigest()


def _valid_channel(value: Any, channel_id: str) -> bool:
    return (
        type(value) is Channel
        and value.channel_id == channel_id
        and isinstance(value.artifact_digest, str)
        and DIGEST.fullmatch(value.artifact_digest) is not None
        and _integer(value.generation)
    )


def create_app(store: Any) -> FastAPI:
    app = FastAPI()

    def close_error(tx: object) -> JSONResponse:
        try:
            store.rollback(tx)
        except Exception:
            pass
        return _error("storage_failure", 503)

    @app.post("/v1/channels/{channel_id}/publish")
    async def publish(channel_id: str, request: Request) -> Response:
        if ID.fullmatch(channel_id) is None:
            return _error("invalid_request", 422)
        try:
            body = await request.json()
        except Exception:
            return _error("invalid_request", 422)
        if not isinstance(body, dict) or set(body) != {
            "request_id",
            "expected_generation",
            "artifact_digest",
        }:
            return _error("invalid_request", 422)
        request_id = body["request_id"]
        expected = body["expected_generation"]
        artifact = body["artifact_digest"]
        if (
            not isinstance(request_id, str)
            or ID.fullmatch(request_id) is None
            or not _integer(expected)
            or not isinstance(artifact, str)
            or DIGEST.fullmatch(artifact) is None
        ):
            return _error("invalid_request", 422)
        fingerprint = _fingerprint(channel_id, body)
        try:
            tx = store.begin()
        except Exception:
            return _error("storage_failure", 503)
        if tx is None:
            return _error("storage_failure", 503)
        try:
            receipt = store.find_receipt(tx, request_id)
            if receipt is not None and type(receipt) is not Receipt:
                raise StoreError("invalid receipt")
            if receipt is not None:
                if receipt.command_fingerprint != fingerprint:
                    store.rollback(tx)
                    return _error("request_id_conflict", 409)
                if (
                    receipt.request_id != request_id
                    or receipt.status_code != 200
                    or not isinstance(receipt.response_body, bytes)
                ):
                    raise StoreError("invalid receipt")
                store.rollback(tx)
                return Response(receipt.response_body, status_code=receipt.status_code, media_type="application/json")
            channel = store.read_channel(tx, channel_id)
            if channel is None:
                store.rollback(tx)
                return _error("channel_not_found", 404)
            if not _valid_channel(channel, channel_id):
                raise StoreError("invalid channel")
            if expected != channel.generation:
                store.rollback(tx)
                return _error("generation_conflict", 409)
            approved = store.artifact_is_approved(tx, artifact)
            if type(approved) is not bool:
                raise StoreError("invalid approval result")
            if not approved:
                store.rollback(tx)
                return _error("artifact_not_approved", 422)
            if channel.generation == MAX:
                store.rollback(tx)
                return _error("generation_overflow", 409)
            generation = channel.generation + 1
            response_body = _json_bytes(
                {
                    "artifact_digest": artifact,
                    "channel_id": channel_id,
                    "generation": generation,
                    "previous_digest": channel.artifact_digest,
                    "request_id": request_id,
                }
            )
            new_channel = Channel(channel_id, artifact, generation)
            event = PublicationEvent(
                request_id,
                channel_id,
                channel.artifact_digest,
                artifact,
                generation,
            )
            new_receipt = Receipt(request_id, fingerprint, 200, response_body)
            store.stage_channel(tx, new_channel)
            store.stage_event(tx, event)
            store.stage_receipt(tx, new_receipt)
            store.commit(tx)
            return Response(response_body, status_code=200, media_type="application/json")
        except Exception:
            return close_error(tx)

    @app.get("/v1/channels/{channel_id}")
    def get_channel(channel_id: str) -> Response:
        if ID.fullmatch(channel_id) is None:
            return _error("invalid_request", 422)
        try:
            tx = store.begin()
            channel = store.read_channel(tx, channel_id)
            store.rollback(tx)
        except Exception:
            return _error("storage_failure", 503)
        if channel is None:
            return _error("channel_not_found", 404)
        if not _valid_channel(channel, channel_id):
            return _error("storage_failure", 503)
        return JSONResponse(
            {
                "artifact_digest": channel.artifact_digest,
                "channel_id": channel.channel_id,
                "generation": channel.generation,
            }
        )

    @app.get("/v1/publication-events")
    def get_events(channel_id: str) -> Response:
        if ID.fullmatch(channel_id) is None:
            return _error("invalid_request", 422)
        try:
            tx = store.begin()
            events = store.list_events(tx, channel_id)
            store.rollback(tx)
        except Exception:
            return _error("storage_failure", 503)
        if not isinstance(events, list) or any(type(event) is not PublicationEvent for event in events):
            return _error("storage_failure", 503)
        return JSONResponse(
            [
                {
                    "artifact_digest": event.artifact_digest,
                    "channel_id": event.channel_id,
                    "generation": event.generation,
                    "previous_digest": event.previous_digest,
                    "request_id": event.request_id,
                }
                for event in events
            ]
        )

    @app.get("/v1/publication-receipts/{request_id}")
    def get_receipt(request_id: str) -> Response:
        if ID.fullmatch(request_id) is None:
            return _error("invalid_request", 422)
        try:
            tx = store.begin()
            receipt = store.find_receipt(tx, request_id)
            store.rollback(tx)
        except Exception:
            return _error("storage_failure", 503)
        if receipt is None:
            return _error("receipt_not_found", 404)
        if type(receipt) is not Receipt:
            return _error("storage_failure", 503)
        return Response(receipt.response_body, status_code=receipt.status_code, media_type="application/json")

    return app

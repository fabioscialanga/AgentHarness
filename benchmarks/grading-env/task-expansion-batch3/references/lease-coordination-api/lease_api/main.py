from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, StrictInt, field_validator
from sqlalchemy import Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

MUTANT = os.getenv("AGENTHARNESS_MUTANT", "")
DB = Path(os.environ.get("LEASE_DB_PATH", Path(__file__).resolve().parents[1] / "leases.db"))
engine = create_engine(f"sqlite:///{DB}", connect_args={"check_same_thread": False, "timeout": 30})
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

class Base(DeclarativeBase): pass
class Lease(Base):
    __tablename__ = "leases"
    resource: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[str] = mapped_column(String)
    token: Mapped[int] = mapped_column(Integer)
    acquired_at: Mapped[str] = mapped_column(String)
    expires_at: Mapped[str] = mapped_column(String)
    released_at: Mapped[str | None] = mapped_column(String, nullable=True)
    last_operation_at: Mapped[str] = mapped_column(String)
Base.metadata.create_all(engine)

app = FastAPI()


def instant(value: str) -> datetime:
    if not isinstance(value, str) or not (value.endswith("Z") or (len(value) >= 6 and value[-6] in "+-" and value[-3] == ":")):
        raise ValueError("explicit offset required")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    if parsed.tzinfo is None: raise ValueError("explicit offset required")
    return parsed.astimezone(timezone.utc)


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

class Acquire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    owner: str; duration_seconds: StrictInt; now: str
    @field_validator("owner")
    @classmethod
    def owner_valid(cls, v: str) -> str:
        if not ID.fullmatch(v): raise ValueError("invalid owner")
        return v
    @field_validator("duration_seconds")
    @classmethod
    def duration_valid(cls, v: int) -> int:
        if not 1 <= v <= 86400: raise ValueError("invalid duration")
        return v
    @field_validator("now")
    @classmethod
    def time_valid(cls, v: str) -> str: instant(v); return v

class Guarded(Acquire): fencing_token: StrictInt
class Release(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    owner: str; fencing_token: StrictInt; now: str
    @field_validator("owner")
    @classmethod
    def owner_valid(cls, v: str) -> str:
        if not ID.fullmatch(v): raise ValueError("invalid owner")
        return v
    @field_validator("now")
    @classmethod
    def time_valid(cls, v: str) -> str: instant(v); return v


def resource_valid(resource: str) -> None:
    if not ID.fullmatch(resource): raise HTTPException(422, "invalid resource")

def status(row: Lease, at: datetime) -> str:
    if row.released_at is not None and at >= instant(row.released_at):
        return "active" if MUTANT == "lease_state_and_failure_atomicity" else "released"
    return "expired" if at >= instant(row.expires_at) else "active"


def actual_status(row: Lease, at: datetime) -> str:
    if row.released_at is not None and at >= instant(row.released_at): return "released"
    return "expired" if at >= instant(row.expires_at) else "active"

def payload(row: Lease, at: datetime) -> dict:
    return {"resource": row.resource, "owner": row.owner, "fencing_token": row.token, "acquired_at": row.acquired_at, "expires_at": row.expires_at, "status": status(row, at)}

def locked_session():
    connection = engine.connect(); connection.exec_driver_sql("BEGIN IMMEDIATE")
    return connection, Session(bind=connection)

def reject_guard(row: Lease, owner: str, token: int) -> None:
    if row.owner != owner: raise HTTPException(412, "wrong owner")
    if row.token != token: raise HTTPException(412, "stale fencing token")

def ensure_monotonic(row: Lease, now: datetime) -> None:
    if now < instant(row.last_operation_at): raise HTTPException(409, "operation time moved backwards")

@app.post("/leases/{resource}/acquire", status_code=201)
def acquire(resource: str, body: Acquire, response: Response):
    resource_valid(resource); now = instant(body.now)
    connection, session = locked_session()
    try:
        row = session.get(Lease, resource)
        if row and actual_status(row, now) == "active":
            # Keep the synthetic mutation pinned to the contention scenario.  A
            # broad mutation made unrelated acquire/atomicity checks fail too,
            # obscuring the one-property mutation-sensitivity contract.
            if MUTANT == "lease_concurrent_contention" and resource == "process-race":
                connection.rollback()
                return {"resource": resource, "owner": body.owner, "fencing_token": row.token, "acquired_at": stamp(now), "expires_at": stamp(now + timedelta(seconds=body.duration_seconds)), "status": "active"}
            raise HTTPException(409, "lease active")
        if row: ensure_monotonic(row, now)
        token = (row.token + 1) if row else 1
        if MUTANT == "lease_acquire_fencing" and resource == "generations" and os.getenv("AGENTHARNESS_CROSS_PROCESS_CHILD") == "1" and row: token = 1
        expires = now + timedelta(seconds=body.duration_seconds)
        if row:
            row.owner = body.owner; row.token = token; row.acquired_at = stamp(now); row.expires_at = stamp(expires); row.released_at = None; row.last_operation_at = stamp(now)
        else:
            row = Lease(resource=resource, owner=body.owner, token=token, acquired_at=stamp(now), expires_at=stamp(expires), released_at=None, last_operation_at=stamp(now)); session.add(row)
        session.flush(); result = payload(row, now); session.commit(); connection.commit(); return result
    except HTTPException:
        session.rollback(); connection.rollback(); raise
    finally: session.close(); connection.close()

@app.post("/leases/{resource}/renew")
def renew(resource: str, body: Guarded):
    resource_valid(resource); now = instant(body.now); connection, session = locked_session()
    try:
        row = session.get(Lease, resource)
        if not row: raise HTTPException(404, "not found")
        ensure_monotonic(row, now)
        if row.released_at is not None or now >= instant(row.expires_at): raise HTTPException(409, "lease inactive")
        # As above, mutation selection changes one normative behavior only.
        if MUTANT == "lease_renewal" and resource == "renew-stale":
            if row.owner != body.owner: raise HTTPException(412, "wrong owner")
        else: reject_guard(row, body.owner, body.fencing_token)
        new_expiry = now + timedelta(seconds=body.duration_seconds)
        if new_expiry <= instant(row.expires_at): raise HTTPException(409, "renewal must extend expiry")
        row.expires_at = stamp(new_expiry); row.last_operation_at = stamp(now)
        session.flush(); result = payload(row, now); session.commit(); connection.commit(); return result
    except HTTPException: session.rollback(); connection.rollback(); raise
    finally: session.close(); connection.close()

@app.post("/leases/{resource}/release")
def release(resource: str, body: Release):
    resource_valid(resource); now = instant(body.now); connection, session = locked_session()
    try:
        row = session.get(Lease, resource)
        if not row: raise HTTPException(404, "not found")
        ensure_monotonic(row, now)
        if row.released_at is not None: raise HTTPException(409, "already released")
        if now >= instant(row.expires_at): raise HTTPException(409, "lease expired")
        if MUTANT == "lease_release_reacquire" and row.owner == body.owner:
            pass
        else:
            reject_guard(row, body.owner, body.fencing_token)
        row.released_at = stamp(now); row.last_operation_at = stamp(now)
        session.flush(); result = payload(row, now); session.commit(); connection.commit(); return result
    except HTTPException: session.rollback(); connection.rollback(); raise
    finally: session.close(); connection.close()

@app.get("/leases/{resource}")
def read(resource: str, as_of: str = Query(...)):
    resource_valid(resource)
    try: at = instant(as_of)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    with Session(engine) as session:
        row = session.get(Lease, resource)
        if not row: raise HTTPException(404, "not found")
        if at < instant(row.acquired_at): raise HTTPException(409, "as_of predates generation")
        return payload(row, at)

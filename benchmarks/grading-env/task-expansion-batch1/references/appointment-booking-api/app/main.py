from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

app = FastAPI()
MUTANT = os.getenv("AGENTHARNESS_MUTANT", "")
DB_PATH = Path(__file__).resolve().parents[1] / "appointments.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


class Base(DeclarativeBase):
    pass


class Appointment(Base):
    __tablename__ = "appointments"
    appointment_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String, nullable=False)
    provider_id: Mapped[str] = mapped_column(String, nullable=False)
    starts_at: Mapped[str] = mapped_column(String, nullable=False)
    ends_at: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    cancel_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


Base.metadata.create_all(engine)


class CreateAppointment(BaseModel):
    customer_id: str
    provider_id: str
    starts_at: str
    ends_at: str
    reason: str


class Reschedule(BaseModel):
    starts_at: str
    ends_at: str


class Cancel(BaseModel):
    reason: str


def parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def payload(item: Appointment) -> dict:
    return {column.name: getattr(item, column.name) for column in Appointment.__table__.columns}


def conflicts(session: Session, provider: str, start: datetime, end: datetime, exclude: int | None = None) -> bool:
    items = session.scalars(select(Appointment).where(Appointment.provider_id == provider, Appointment.status == "scheduled")).all()
    for item in items:
        if item.appointment_id == exclude:
            continue
        other_start, other_end = parse(item.starts_at), parse(item.ends_at)
        overlap = start <= other_end and other_start <= end if MUTANT == "appointment_provider_conflicts" else start < other_end and other_start < end
        if overlap:
            return True
    return False


@app.post("/appointments", status_code=201)
def create(body: CreateAppointment):
    try:
        start, end = parse(body.starts_at), parse(body.ends_at)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if MUTANT != "appointment_interval_validation" and end <= start:
        raise HTTPException(422, "invalid interval")
    with Session(engine) as session:
        if conflicts(session, body.provider_id, start, end):
            raise HTTPException(409, "provider conflict")
        item = Appointment(customer_id=body.customer_id, provider_id=body.provider_id, starts_at=start.isoformat().replace("+00:00", "Z"), ends_at=end.isoformat().replace("+00:00", "Z"), reason=body.reason, status="scheduled", cancel_reason=None, cancelled_at=None, created_at=now())
        session.add(item)
        if MUTANT == "appointment_create_and_filters" and os.getenv("AGENTHARNESS_CROSS_PROCESS_CHILD") == "1":
            session.flush()
            result = payload(item)
            session.rollback()
            return result
        session.commit()
        session.refresh(item)
        return payload(item)


@app.get("/appointments")
def list_items(customer_id: str | None = None, provider_id: str | None = None, status: str | None = None):
    with Session(engine) as session:
        statement = select(Appointment)
        if MUTANT != "appointment_create_and_filters":
            if customer_id is not None:
                statement = statement.where(Appointment.customer_id == customer_id)
            if provider_id is not None:
                statement = statement.where(Appointment.provider_id == provider_id)
            if status is not None:
                statement = statement.where(Appointment.status == status)
        return [payload(item) for item in session.scalars(statement.order_by(Appointment.appointment_id)).all()]


@app.get("/appointments/{appointment_id}")
def detail(appointment_id: int):
    with Session(engine) as session:
        item = session.get(Appointment, appointment_id)
        if item is None:
            raise HTTPException(404, "not found")
        return payload(item)


@app.patch("/appointments/{appointment_id}/reschedule")
def reschedule(appointment_id: int, body: Reschedule):
    with Session(engine) as session:
        item = session.get(Appointment, appointment_id)
        if item is None:
            raise HTTPException(404, "not found")
        if item.status != "scheduled":
            raise HTTPException(409, "terminal")
        try:
            start, end = parse(body.starts_at), parse(body.ends_at)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if end <= start:
            raise HTTPException(422, "invalid interval")
        if MUTANT == "appointment_reschedule_atomic":
            item.starts_at = start.isoformat().replace("+00:00", "Z")
            item.ends_at = end.isoformat().replace("+00:00", "Z")
            session.commit()
        if conflicts(session, item.provider_id, start, end, appointment_id):
            raise HTTPException(409, "provider conflict")
        item.starts_at = start.isoformat().replace("+00:00", "Z")
        item.ends_at = end.isoformat().replace("+00:00", "Z")
        session.commit()
        session.refresh(item)
        return payload(item)


@app.post("/appointments/{appointment_id}/cancel")
def cancel(appointment_id: int, body: Cancel):
    with Session(engine) as session:
        item = session.get(Appointment, appointment_id)
        if item is None:
            raise HTTPException(404, "not found")
        if item.status != "scheduled":
            raise HTTPException(409, "terminal")
        item.status = "cancelled"
        item.cancel_reason = body.reason
        item.cancelled_at = now()
        if MUTANT == "appointment_cancel_releases_slot":
            item.status = "scheduled"
        session.commit()
        session.refresh(item)
        return payload(item)

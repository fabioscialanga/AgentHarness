from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

app = FastAPI()
MUTANT = os.getenv("AGENTHARNESS_MUTANT", "")
TRANSITIONS = ["picked_up", "in_transit", "out_for_delivery", "delivered"]
DB_PATH = Path(__file__).resolve().parents[1] / "shipments.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


class Base(DeclarativeBase):
    pass


class Shipment(Base):
    __tablename__ = "shipments"
    tracking_number: Mapped[str] = mapped_column(String, primary_key=True)
    carrier: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)


class ShipmentEvent(Base):
    __tablename__ = "shipment_events"
    __table_args__ = (UniqueConstraint("tracking_number", "event_id"),)
    row_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracking_number: Mapped[str] = mapped_column(ForeignKey("shipments.tracking_number"), nullable=False)
    event_id: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str] = mapped_column(String, nullable=False)


Base.metadata.create_all(engine)


class CreateShipment(BaseModel):
    tracking_number: str
    carrier: str


class AddEvent(BaseModel):
    event_id: str
    type: str
    occurred_at: str
    location: str


def parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


def event_payload(item: ShipmentEvent) -> dict:
    return {"event_id": item.event_id, "type": item.type, "occurred_at": item.occurred_at, "location": item.location}


def shipment_payload(session: Session, item: Shipment) -> dict:
    events = session.scalars(select(ShipmentEvent).where(ShipmentEvent.tracking_number == item.tracking_number).order_by(ShipmentEvent.row_id)).all()
    return {"tracking_number": item.tracking_number, "carrier": item.carrier, "status": item.status, "events": [event_payload(event) for event in events]}


@app.post("/shipments", status_code=201)
def create(body: CreateShipment):
    with Session(engine) as session:
        if session.get(Shipment, body.tracking_number) is not None:
            raise HTTPException(409, "duplicate tracking number")
        item = Shipment(tracking_number=body.tracking_number, carrier=body.carrier, status="created")
        session.add(item)
        if MUTANT == "shipment_create_and_filters" and os.getenv("AGENTHARNESS_CROSS_PROCESS_CHILD") == "1":
            session.flush()
            result = shipment_payload(session, item)
            session.rollback()
            return result
        session.commit()
        return shipment_payload(session, item)


@app.get("/shipments")
def list_items(carrier: str | None = None, status: str | None = None):
    with Session(engine) as session:
        statement = select(Shipment)
        if MUTANT != "shipment_create_and_filters":
            if carrier is not None:
                statement = statement.where(Shipment.carrier == carrier)
            if status is not None:
                statement = statement.where(Shipment.status == status)
        items = session.scalars(statement.order_by(Shipment.tracking_number)).all()
        return [shipment_payload(session, item) for item in items]


@app.get("/shipments/{tracking_number}")
def detail(tracking_number: str):
    with Session(engine) as session:
        item = session.get(Shipment, tracking_number)
        if item is None:
            raise HTTPException(404, "not found")
        return shipment_payload(session, item)


@app.post("/shipments/{tracking_number}/events", status_code=201)
def add_event(tracking_number: str, body: AddEvent):
    with Session(engine) as session:
        item = session.get(Shipment, tracking_number)
        if item is None:
            raise HTTPException(404, "not found")
        prior = session.scalar(select(ShipmentEvent).where(ShipmentEvent.tracking_number == tracking_number, ShipmentEvent.event_id == body.event_id))
        incoming = {"event_id": body.event_id, "type": body.type, "occurred_at": body.occurred_at, "location": body.location}
        if prior is not None:
            if event_payload(prior) == incoming:
                if MUTANT == "shipment_event_idempotency":
                    prior.location = "MUTATED-ON-REPLAY"
                    session.commit()
                return shipment_payload(session, item)
            raise HTTPException(409, "event id conflict")
        if item.status == "delivered" and MUTANT != "shipment_time_and_terminal_invariants":
            raise HTTPException(409, "terminal")
        expected_index = 0 if item.status == "created" else TRANSITIONS.index(item.status) + 1
        if MUTANT != "shipment_skipped_transition_atomic" and (expected_index >= len(TRANSITIONS) or body.type != TRANSITIONS[expected_index]):
            raise HTTPException(409, "invalid transition")
        try:
            timestamp = parse(body.occurred_at)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        previous = session.scalar(select(ShipmentEvent).where(ShipmentEvent.tracking_number == tracking_number).order_by(ShipmentEvent.row_id.desc()))
        if previous is not None and MUTANT != "shipment_time_and_terminal_invariants" and timestamp <= parse(previous.occurred_at):
            raise HTTPException(409, "stale event")
        session.add(ShipmentEvent(tracking_number=tracking_number, **incoming))
        item.status = "created" if MUTANT == "shipment_valid_transition_path" and tracking_number == "TRK-PATH-37" else body.type
        session.commit()
        return shipment_payload(session, item)

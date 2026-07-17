from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

MUTANT = os.getenv("AGENTHARNESS_MUTANT", "")
DB = Path(os.environ.get("LEDGER_DB_PATH", Path(__file__).resolve().parents[1] / "ledger.db"))
engine = create_engine(f"sqlite:///{DB}", connect_args={"check_same_thread": False, "timeout": 30})
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
AMOUNT = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?$")

class Base(DeclarativeBase): pass
class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String, primary_key=True); currency: Mapped[str] = mapped_column(String)
class Transaction(Base):
    __tablename__ = "transactions"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String, unique=True); idempotency_key: Mapped[str] = mapped_column(String, index=True)
    currency: Mapped[str] = mapped_column(String); canonical_payload: Mapped[str] = mapped_column(Text); reverses: Mapped[str | None] = mapped_column(String, nullable=True)
class Entry(Base):
    __tablename__ = "entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(String, ForeignKey("transactions.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer); account_id: Mapped[str] = mapped_column(String, index=True)
    # The public decimal grammar has no upper bound, so do not inherit
    # SQLite's signed 64-bit integer limit for minor units.
    direction: Mapped[str] = mapped_column(String); amount_cents: Mapped[str] = mapped_column(Text)
Base.metadata.create_all(engine)
app = FastAPI()


def id_valid(value: str) -> str:
    if not ID.fullmatch(value): raise ValueError("invalid id")
    return value

def cents(value: str) -> int:
    if not isinstance(value, str) or not AMOUNT.fullmatch(value): raise ValueError("invalid amount")
    whole, _, fraction = value.partition(".")
    parsed = int(whole + (fraction + "00")[:2])
    if parsed <= 0: raise ValueError("amount must be positive")
    return parsed

def amount(value: int) -> str: return f"{value // 100}.{value % 100:02d}"

class AccountBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str; currency: str
    @field_validator("id")
    @classmethod
    def valid_id(cls, v: str) -> str: return id_valid(v)
    @field_validator("currency")
    @classmethod
    def valid_currency(cls, v: str) -> str:
        valid = bool(re.fullmatch(r"[A-Z]{3}", v))
        if MUTANT == "ledger_account_identity" and re.fullmatch(r"[a-z]{2}", v): valid = True
        if not valid: raise ValueError("currency must be three uppercase ASCII letters")
        return v
class EntryBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    account_id: str; direction: str; amount: str
    @field_validator("account_id")
    @classmethod
    def valid_id(cls, v: str) -> str: return id_valid(v)
    @field_validator("direction")
    @classmethod
    def valid_direction(cls, v: str) -> str:
        if v not in ("debit", "credit"): raise ValueError("invalid direction")
        return v
    @field_validator("amount")
    @classmethod
    def valid_amount(cls, v: str) -> str: cents(v); return v
class Posting(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    entries: list[EntryBody]

def locked_session():
    connection = engine.connect(); connection.exec_driver_sql("BEGIN IMMEDIATE")
    return connection, Session(bind=connection)

def canonical_entries(entries: list[EntryBody]) -> list[dict]:
    result = [{"account_id": e.account_id, "direction": e.direction, "amount": amount(cents(e.amount))} for e in entries]
    return sorted(result, key=lambda e: (e["account_id"], e["direction"], e["amount"]))
def canonical_text(entries: list[dict]) -> str: return json.dumps({"entries": entries}, sort_keys=True, separators=(",", ":"))
def tx_payload(session: Session, tx: Transaction) -> dict:
    rows = list(session.scalars(select(Entry).where(Entry.transaction_id == tx.id).order_by(Entry.ordinal)))
    return {"id": tx.id, "idempotency_key": tx.idempotency_key, "currency": tx.currency, "entries": [{"account_id": e.account_id, "direction": e.direction, "amount": amount(int(e.amount_cents))} for e in rows], "reverses": tx.reverses}
def existing_key(session: Session, key: str) -> Transaction | None:
    return session.scalar(select(Transaction).where(Transaction.idempotency_key == key).order_by(Transaction.sequence))

def validate_key(value: str | None) -> str:
    if value is None: raise HTTPException(422, "Idempotency-Key required")
    try: return id_valid(value)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc

def commit_posting(session: Session, key: str, entries: list[dict], currency: str, reverses: str | None = None) -> Transaction:
    tx = Transaction(id=str(uuid.uuid4()), idempotency_key=key, currency=currency, canonical_payload=canonical_text(entries), reverses=reverses)
    session.add(tx); session.flush()
    for ordinal, e in enumerate(entries): session.add(Entry(transaction_id=tx.id, ordinal=ordinal, account_id=e["account_id"], direction=e["direction"], amount_cents=str(cents(e["amount"]))))
    session.flush(); return tx

@app.post("/accounts", status_code=201)
def create_account(body: AccountBody):
    connection, session = locked_session()
    try:
        if session.get(Account, body.id): raise HTTPException(409, "account exists")
        row = Account(id=body.id, currency=body.currency); session.add(row); session.commit(); connection.commit(); return {"id": row.id, "currency": row.currency}
    except HTTPException: session.rollback(); connection.rollback(); raise
    finally: session.close(); connection.close()
@app.get("/accounts/{account_id}")
def get_account(account_id: str):
    with Session(engine) as session:
        row = session.get(Account, account_id)
        if not row: raise HTTPException(404, "not found")
        return {"id": row.id, "currency": row.currency}

@app.post("/transactions", status_code=201)
def post_transaction(body: Posting, response: Response, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    key = validate_key(idempotency_key); entries = canonical_entries(body.entries)
    if len(entries) < 2: raise HTTPException(422, "at least two entries required")
    canonical = canonical_text(entries); connection, session = locked_session()
    try:
        prior = existing_key(session, key)
        if prior and MUTANT != "ledger_idempotency_conflict":
            if prior.canonical_payload != canonical or prior.reverses is not None: raise HTTPException(409, "idempotency conflict")
            payload = tx_payload(session, prior); connection.rollback(); response.status_code = 200; return payload
        accounts = {e["account_id"]: session.get(Account, e["account_id"]) for e in entries}
        if any(v is None for v in accounts.values()): raise HTTPException(422, "unknown account")
        currencies = {v.currency for v in accounts.values() if v is not None}
        if len(currencies) != 1: raise HTTPException(422, "mixed currencies")
        debits = sum(cents(e["amount"]) for e in entries if e["direction"] == "debit"); credits = sum(cents(e["amount"]) for e in entries if e["direction"] == "credit")
        if MUTANT != "ledger_balanced_posting" and debits != credits: raise HTTPException(422, "unbalanced transaction")
        tx = commit_posting(session, key, entries, next(iter(currencies))); result = tx_payload(session, tx); session.commit(); connection.commit(); return result
    except HTTPException: session.rollback(); connection.rollback(); raise
    finally: session.close(); connection.close()

@app.get("/transactions/{transaction_id}")
def get_transaction(transaction_id: str):
    with Session(engine) as session:
        tx = session.scalar(select(Transaction).where(Transaction.id == transaction_id))
        if not tx: raise HTTPException(404, "not found")
        return tx_payload(session, tx)
@app.get("/accounts/{account_id}/balance")
def balance(account_id: str):
    with Session(engine) as session:
        account = session.get(Account, account_id)
        if not account: raise HTTPException(404, "not found")
        rows = list(session.scalars(select(Entry).where(Entry.account_id == account_id)))
        value = sum(int(e.amount_cents) if e.direction == "credit" else -int(e.amount_cents) for e in rows)
        sign = "-" if value < 0 else ""; absolute = abs(value)
        return {"account_id": account_id, "currency": account.currency, "balance": f"{sign}{absolute // 100}.{absolute % 100:02d}"}
@app.get("/accounts/{account_id}/journal")
def journal(account_id: str):
    with Session(engine) as session:
        if not session.get(Account, account_id): raise HTTPException(404, "not found")
        rows = list(session.execute(select(Entry, Transaction).join(Transaction, Entry.transaction_id == Transaction.id).where(Entry.account_id == account_id).order_by(Transaction.sequence, Entry.ordinal)))
        records = [{"transaction_id": tx.id, "sequence": tx.sequence, "account_id": entry.account_id, "direction": entry.direction, "amount": amount(int(entry.amount_cents))} for entry, tx in rows]
        if MUTANT == "ledger_balances_and_journal":
            grouped: dict[int, list[dict]] = {}
            for record in records: grouped.setdefault(record["sequence"], []).append(record)
            records = [r for seq in sorted(grouped) for r in reversed(grouped[seq])]
        return {"account_id": account_id, "entries": records}

@app.post("/transactions/{transaction_id}/reverse", status_code=201)
def reverse(transaction_id: str, response: Response, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    key = validate_key(idempotency_key); connection, session = locked_session()
    try:
        original = session.scalar(select(Transaction).where(Transaction.id == transaction_id))
        if not original: raise HTTPException(404, "not found")
        prior_key = existing_key(session, key)
        if prior_key:
            if prior_key.reverses == transaction_id:
                result = tx_payload(session, prior_key); connection.rollback(); response.status_code = 200; return result
            raise HTTPException(409, "idempotency conflict")
        prior_reversal = session.scalar(select(Transaction).where(Transaction.reverses == transaction_id).order_by(Transaction.sequence))
        if prior_reversal and MUTANT != "ledger_compensating_reversal": raise HTTPException(409, "already reversed")
        source = list(session.scalars(select(Entry).where(Entry.transaction_id == transaction_id).order_by(Entry.ordinal)))
        entries = sorted([{"account_id": e.account_id, "direction": "credit" if e.direction == "debit" else "debit", "amount": amount(int(e.amount_cents))} for e in source], key=lambda e: (e["account_id"], e["direction"], e["amount"]))
        tx = commit_posting(session, key, entries, original.currency, transaction_id); result = tx_payload(session, tx); session.commit(); connection.commit(); return result
    except HTTPException: session.rollback(); connection.rollback(); raise
    finally: session.close(); connection.close()

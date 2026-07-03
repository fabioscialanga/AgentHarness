from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()


class RefundCreate(BaseModel):
    order_id: str
    amount: float
    currency: str
    reason: str
    requested_by: str


class ReviewPayload(BaseModel):
    decision: str
    approver: str
    note: str


refunds: dict[int, dict] = {}
next_id = 1


def clone_refund(item: dict) -> dict:
    return deepcopy(item)


@app.post("/refunds", status_code=201)
def create_refund(payload: RefundCreate):
    global next_id
    if payload.amount <= 0:
        raise HTTPException(status_code=422, detail="invalid amount")
    if payload.amount <= 50:
        status = "approved"
    else:
        status = "pending_manager"
    record = {
        "id": next_id,
        "order_id": payload.order_id,
        "amount": payload.amount,
        "currency": payload.currency,
        "reason": payload.reason,
        "requested_by": payload.requested_by,
        "status": status,
        "manager_approver": None,
        "manager_note": None,
        "finance_approver": None,
        "finance_note": None,
    }
    refunds[next_id] = record
    next_id += 1
    return clone_refund(record)


@app.get("/refunds")
def list_refunds(status: str | None = None, requested_by: str | None = None):
    items = list(refunds.values())
    if status is not None:
        items = [item for item in items if item["status"] == status]
    if requested_by is not None:
        items = [item for item in items if item["requested_by"] == requested_by]
    items.sort(key=lambda item: item["id"])
    return [clone_refund(item) for item in items]


@app.get("/refunds/{refund_id}")
def get_refund(refund_id: int):
    item = refunds.get(refund_id)
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    return clone_refund(item)


@app.post("/refunds/{refund_id}/manager-review")
def manager_review(refund_id: int, payload: ReviewPayload):
    item = refunds.get(refund_id)
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    if payload.decision not in {"approve", "reject"}:
        raise HTTPException(status_code=422, detail="invalid decision")
    if item["status"] in {"approved", "rejected"}:
        raise HTTPException(status_code=409, detail="terminal state")
    if item["amount"] <= 50:
        raise HTTPException(status_code=409, detail="small refunds do not need manager review")
    if payload.decision == "reject":
        item["status"] = "rejected"
    elif item["amount"] > 500:
        item["status"] = "pending_finance"
    else:
        item["status"] = "approved"
    item["manager_approver"] = payload.approver
    item["manager_note"] = payload.note
    return clone_refund(item)


@app.post("/refunds/{refund_id}/finance-review")
def finance_review(refund_id: int, payload: ReviewPayload):
    item = refunds.get(refund_id)
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    if payload.decision not in {"approve", "reject"}:
        raise HTTPException(status_code=422, detail="invalid decision")
    if item["status"] in {"approved", "rejected"}:
        raise HTTPException(status_code=409, detail="terminal state")
    if item["status"] != "pending_finance":
        raise HTTPException(status_code=409, detail="finance review not allowed yet")
    item["status"] = "approved" if payload.decision == "approve" else "rejected"
    item["finance_approver"] = payload.approver
    item["finance_note"] = payload.note
    return clone_refund(item)

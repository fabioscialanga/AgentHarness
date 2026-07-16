from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

MUTANT = os.getenv("AGENTHARNESS_MUTANT", "")
CENT = Decimal("0.01")


def money(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid amount") from exc
    if parsed <= 0 or parsed.quantize(CENT) != parsed:
        raise ValueError("invalid amount")
    return parsed


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--invoices", required=True)
    parser.add_argument("--payments", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    try:
        cutoff = date.fromisoformat(args.as_of)
        invoice_rows = read_rows(Path(args.invoices))
        payment_rows = read_rows(Path(args.payments))
        invoices: dict[str, dict] = {}
        for row in invoice_rows:
            invoice_id = row["invoice_id"]
            issued = date.fromisoformat(row["issued_date"])
            due = date.fromisoformat(row["due_date"])
            amount = money(row["amount"])
            if not invoice_id or not row["customer_id"] or issued > due or invoice_id in invoices:
                raise ValueError("invalid invoice")
            invoices[invoice_id] = {"invoice_id": invoice_id, "customer_id": row["customer_id"], "issued": issued, "amount": amount, "paid": Decimal("0.00")}
    except (OSError, KeyError, ValueError) as exc:
        print(f"invalid input: {exc}", file=sys.stderr)
        return 2

    acquired: set[str] = set()
    unmatched: list[tuple[int, dict[str, str]]] = []
    duplicate_count = 0
    try:
        for line_number, row in enumerate(payment_rows, 2):
            payment_id = row["payment_id"]
            payment_date = date.fromisoformat(row["payment_date"])
            amount = money(row["amount"])
            if not payment_id or not row["invoice_id"]:
                raise ValueError("invalid payment")
            if payment_date > cutoff:
                if MUTANT == "reconciliation_cutoff_and_duplicates":
                    pass
                else:
                    continue
            if payment_id in acquired:
                duplicate_count += 1
                unmatched.append((line_number, {**row, "reason": "duplicate_payment_id"}))
                continue
            acquired.add(payment_id)
            invoice = invoices.get(row["invoice_id"])
            if invoice is None:
                unmatched.append((line_number, {**row, "reason": "unknown_invoice"}))
            else:
                invoice["paid"] += amount
    except (KeyError, ValueError) as exc:
        print(f"invalid input: {exc}", file=sys.stderr)
        return 2

    report = []
    for invoice_id in sorted(invoices):
        invoice = invoices[invoice_id]
        if invoice["issued"] > cutoff:
            continue
        amount = invoice["amount"]
        paid = invoice["paid"]
        balance = amount - paid
        if paid == 0:
            status = "OPEN"
        elif paid < amount:
            status = "PARTIAL"
        elif paid == amount:
            status = "PAID"
        else:
            status = "OVERPAID"
        if MUTANT == "reconciliation_status_and_decimals" and status == "OVERPAID":
            balance, status = Decimal("0.00"), "PAID"
        report.append({"invoice_id": invoice_id, "customer_id": invoice["customer_id"], "invoice_amount": f"{amount:.2f}", "paid_amount": f"{paid:.2f}", "balance": f"{balance:.2f}", "status": status})
    if MUTANT == "reconciliation_rows_and_order":
        report.reverse()
    unmatched.sort(key=lambda pair: (pair[1]["payment_id"], pair[0]))
    unmatched_rows = [row for _, row in unmatched]
    if MUTANT == "reconciliation_unmatched_reporting":
        unmatched_rows = []
    totals = {
        "as_of": args.as_of,
        "invoice_count": len(report),
        "open_count": sum(row["status"] == "OPEN" for row in report),
        "partial_count": sum(row["status"] == "PARTIAL" for row in report),
        "paid_count": sum(row["status"] == "PAID" for row in report),
        "overpaid_count": sum(row["status"] == "OVERPAID" for row in report),
        "total_invoice_amount": f"{sum((Decimal(row['invoice_amount']) for row in report), Decimal('0.00')):.2f}",
        "total_paid_amount": f"{sum((Decimal(row['paid_amount']) for row in report), Decimal('0.00')):.2f}",
        "total_balance": f"{sum((Decimal(row['balance']) for row in report), Decimal('0.00')):.2f}",
        "unmatched_payment_count": len(unmatched_rows),
        "duplicate_payment_count": duplicate_count,
    }
    if MUTANT == "reconciliation_summary_and_validation":
        totals["invoice_count"] += 1
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "reconciliation.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["invoice_id", "customer_id", "invoice_amount", "paid_amount", "balance", "status"])
        writer.writeheader()
        writer.writerows(report)
    with (out / "unmatched_payments.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["payment_id", "invoice_id", "payment_date", "amount", "reason"])
        writer.writeheader()
        writer.writerows(unmatched_rows)
    (out / "summary.json").write_text(json.dumps(totals, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

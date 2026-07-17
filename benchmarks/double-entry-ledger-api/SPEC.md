# double-entry-ledger-api

## Objective

Immutable balanced double-entry posting with idempotency, derived balances, and compensating reversal.

## Required stack

Python 3.12, FastAPI, Pydantic, SQLAlchemy, SQLite, pytest

## Public interface and behavior

- POST /accounts body exact id,currency returns 201 exact id,currency; GET /accounts/{id} returns the same exact object; IDs match [A-Za-z0-9][A-Za-z0-9._-]{0,63}; no account update or delete route
- parse with exact Decimal, require grammar and value, then render exactly two fractional digits; 1, 1.0, and 1.00 are one canonical amount and response entries use that form
- sum debit amounts must equal sum credit amounts exactly in decimal arithmetic; reported account balance is total credits minus total debits
- account currency is exactly three uppercase ASCII letters; every transaction is single-currency and all referenced accounts must share that currency
- positive base-10 string matching 0|[1-9][0-9]* followed optionally by dot and one or two digits; value must be greater than zero; signs, exponent, locale separators, leading zeroes, NaN, and infinity are invalid
- ledger_api.main:app with SQLite path from LEDGER_DB_PATH
- all invalid, stale, duplicate-conflict, and losing concurrent operations preserve complete accounts, transactions, entries, and derived balances
- canonical payload normalizes amounts to two decimals and sorts entries by account_id,direction,canonical amount; initial commit returns 201, same key plus same canonical payload returns 200 with the same transaction, and same key plus different payload returns 409
- POST /transactions with Idempotency-Key matching the ID grammar and exact body entries; each exact entry is account_id,direction,amount where direction is debit or credit
- GET /transactions/{id} returns the exact transaction schema; GET /accounts/{id}/balance returns exact account_id,currency,balance; GET /accounts/{id}/journal returns exact account_id,entries where each exact record is transaction_id,sequence,account_id,direction,amount ordered by transaction sequence then canonical entry order
- POST /transactions/{id}/reverse with Idempotency-Key appends one linked transaction with every debit/credit swapped; initial success is 201, replay with the same key is 200 with the same reversal, another key after reversal is 409; no original row is edited or deleted
- exact id,idempotency_key,currency,entries,reverses object; entries use the exact entry schema and canonical amount; reverses is null or the original transaction ID

## Packaging and quality requirements

- The workspace root is the runnable project.
- Keep the importable implementation in the package named by the public entrypoint.
- Declare runtime and test dependencies in pyproject.toml.
- Include automated tests and exact run instructions.
- Do not use network services, implicit wall-clock time, or files outside the workspace.
- Invalid input must produce a controlled CLI failure or HTTP 4xx response, not an uncaught traceback.

# Cloned-start mechanism evidence

This directory preserves the compact result of a deterministic one-pair mechanism check executed on 2026-08-18.

Design:

1. `A-control` and `B-agentharness` were byte-identical copies of the intentionally defective calculator fixture.
2. The external behavioral plan produced the same actionable `adds_negative_numbers` finding in both copies.
3. The control received no feedback and no repair invocation.
4. One external repair agent invocation received only the AgentHarness report and was required to write a repair-response contract.
5. The declared and actual solution diff both contained only `calculator.py`.
6. The original finding remained failed in A and changed from failed to passed in B.
7. A mixed-sign heldout check, created outside the workspaces and not delivered to the repair agent, failed in A and passed in B.
8. Plan, test-bundle, and feedback hashes remained stable.

`result.json` records every original gate. `hardened-recheck.json` records the visible, heldout, contract, and diff assertions rerun with the final 0.2.0 verifier after integrity hardening. `heldout-plan.json` and `heldout-tests/` preserve the heldout endpoint used after the repair invocation.

Claim boundary: this establishes that the complete finding → adoption → diff → resolution → heldout chain can operate from a cloned start. It is not evidence of average efficacy, superiority over generic self-repair, or performance across tasks and providers.

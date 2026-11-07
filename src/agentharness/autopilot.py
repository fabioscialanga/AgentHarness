"""Deterministic, advisory-only M2 prototype decision."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    reason: str
    message: str


def decide_stop(changed_paths: tuple[str, ...]) -> Decision | None:
    significant = tuple(
        path for path in changed_paths
        if path in {"pyproject.toml", "SECURITY.md"} or path.startswith(".github/workflows/")
    )
    if not significant:
        return None
    names = ", ".join(significant[:3])
    if len(significant) > 3:
        names += f" (+{len(significant) - 3})"
    return Decision(
        reason="project_governance_change",
        message=f"AgentHarness: modificati {names}. Valuta un controllo mirato prima del rilascio.",
    )

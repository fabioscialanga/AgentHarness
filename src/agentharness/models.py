from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CommandArtifact:
    cmd: str
    exit_code: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CommandArtifact":
        return cls(
            cmd=str(payload.get("cmd", "")),
            exit_code=payload.get("exit_code"),
            stdout_path=payload.get("stdout_path"),
            stderr_path=payload.get("stderr_path"),
        )


@dataclass
class OutputArtifact:
    type: str
    path: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OutputArtifact":
        return cls(
            type=str(payload.get("type", "file")),
            path=str(payload.get("path", "")),
        )


@dataclass
class RunRecord:
    run_id: str
    workspace: Path
    changed_files: list[str] = field(default_factory=list)
    commands: list[CommandArtifact] = field(default_factory=list)
    outputs: list[OutputArtifact] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunRecord":
        artifacts = payload.get("artifacts", {})
        return cls(
            run_id=str(payload.get("run_id", "")),
            workspace=Path(payload.get("workspace", ".")),
            changed_files=[str(item) for item in artifacts.get("changed_files", [])],
            commands=[CommandArtifact.from_dict(item) for item in artifacts.get("commands", [])],
            outputs=[OutputArtifact.from_dict(item) for item in artifacts.get("outputs", [])],
            raw=payload,
        )


@dataclass
class Claim:
    id: str
    type: str
    statement: str
    expected: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Claim":
        return cls(
            id=str(payload.get("id", "")),
            type=str(payload.get("type", "")),
            statement=str(payload.get("statement", "")),
            expected=dict(payload.get("expected", {})),
        )


@dataclass
class ClaimsDocument:
    run_id: str
    claims: list[Claim]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ClaimsDocument":
        return cls(
            run_id=str(payload.get("run_id", "")),
            claims=[Claim.from_dict(item) for item in payload.get("claims", [])],
        )


@dataclass
class ClaimResult:
    claim_id: str
    status: str
    reason: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "status": self.status,
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclass
class VerifyRunResult:
    run_id: str
    run_path: Path
    claims_path: Path
    results: list[ClaimResult]
    notes: list[str] = field(default_factory=list)
    report_written: str | None = None

    @property
    def summary(self) -> dict[str, int]:
        counts = {"supported": 0, "unsupported": 0, "inconclusive": 0, "invalid": 0}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return counts

    @property
    def ok(self) -> bool:
        return self.summary.get("unsupported", 0) == 0 and self.summary.get("invalid", 0) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_path": str(self.run_path),
            "claims_path": str(self.claims_path),
            "ok": self.ok,
            "summary": self.summary,
            "results": [item.to_dict() for item in self.results],
            "notes": self.notes,
            "report_written": self.report_written,
        }

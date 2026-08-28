from __future__ import annotations

import shutil
from pathlib import Path

SELECTORS = (
    'os.environ.get("AGENTHARNESS_MUTANT", "")',
    'os.environ.get("AGENTHARNESS_MUTANT")',
)
MODULES = {
    "rotating-key-token-verifier": Path("rotating_token/verify.py"),
    "envelope-context-decryptor": Path("envelope_crypto/decrypt.py"),
    "attenuated-capability-verifier": Path("capability/verify.py"),
    "atomic-batch-state-machine": Path("batch_state_api/main.py"),
    "ack-token-work-queue": Path("ack_queue/cli.py"),
    "length-prefixed-frame-parser": Path("frame_parser/parse.py"),
    "streaming-csv-quoted-records": Path("csv_stream/parse.py"),
    "epoch-guarded-leader-heartbeat": Path("epoch_leader/cli.py"),
    "context-complete-authorization-cache": Path("decision_cache/app.py"),
}


def materialize_mutant(reference: Path, task_id: str, mutant_id: str, destination: Path) -> Path:
    """Create a source-level singleton variant; no runtime mutation environment is used."""
    if task_id not in MODULES:
        raise ValueError(f"unknown task: {task_id}")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(reference, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "build", "*.egg-info", ".pytest_cache"))
    module = destination / MODULES[task_id]
    source = module.read_text(encoding="utf-8")
    occurrences = sum(source.count(selector) for selector in SELECTORS)
    if occurrences == 0:
        raise RuntimeError(f"reference has no private mutation selector: {task_id}")
    for selector in SELECTORS:
        source = source.replace(selector, repr(mutant_id))
    if any(selector in source for selector in SELECTORS):
        raise RuntimeError("mutation selector survived materialization")
    module.write_text(source, encoding="utf-8")
    return destination

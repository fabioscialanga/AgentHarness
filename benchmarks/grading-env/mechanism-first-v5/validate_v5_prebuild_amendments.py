from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARENT = "01a331c23895b764f84952d266350fa50e581007e9950039973e8ea3c42e816c"
EXPECTED_IDS = {
    "v5-frame-parser-chunks-file-carrier",
    "v5-csv-stream-chunks-file-carrier",
}


def canonical_payload_hash(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("payload_sha256")
    encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    pointer = json.loads((ROOT / "V5_PREBUILD_AMENDMENTS.json").read_text())
    assert pointer["schema_version"] == 1
    assert pointer["parent_json_sha256"] == PARENT
    rows = pointer["amendments"]
    assert len(rows) == 2
    assert {row["amendment_id"] for row in rows} == EXPECTED_IDS
    digests: list[str] = []
    for row in rows:
        path = ROOT / row["file"]
        payload = json.loads(path.read_text())
        actual = canonical_payload_hash(payload)
        assert actual == payload["payload_sha256"] == row["payload_sha256"]
        assert path.name.endswith(f".{actual}.json")
        parent = payload.get("parent_json_sha256", payload.get("parent_ledger_payload_sha256"))
        assert parent == PARENT
        provider_calls = payload.get("provider_calls", payload.get("provider_calls_observed"))
        efficacy_cells = payload.get("efficacy_cells_observed")
        assert provider_calls == efficacy_cells == 0
        assert payload["status"].startswith("pre_data")
        assert payload["scope"]["candidate_id"] in {"length-prefixed-frame-parser", "streaming-csv-quoted-records"}
        digests.append(actual)
    print(json.dumps({"amendments": 2, "ok": True, "parent_json_sha256": PARENT, "payload_sha256": sorted(digests)}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

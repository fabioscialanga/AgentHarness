from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PARENT="01a331c23895b764f84952d266350fa50e581007e9950039973e8ea3c42e816c"


def main() -> int:
    pointer=json.loads((ROOT/"V5_PREBUILD_AMENDMENTS.json").read_text())
    assert pointer["schema_version"]==1 and pointer["parent_json_sha256"]==PARENT
    assert len(pointer["amendments"])==1
    row=pointer["amendments"][0]; path=ROOT/row["file"]
    payload=json.loads(path.read_text()); claimed=payload.pop("payload_sha256")
    actual=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    assert actual==claimed==row["payload_sha256"]
    assert path.name.endswith(f".{actual}.json")
    assert payload["parent_json_sha256"]==PARENT and payload["efficacy_cells_observed"]==payload["provider_calls"]==0
    assert payload["scope"]=={"candidate_id":"length-prefixed-frame-parser","changes_mechanism_or_checks":False,"transport_only":True}
    print(json.dumps({"amendments":1,"ok":True,"parent_json_sha256":PARENT,"payload_sha256":actual},sort_keys=True,separators=(",",":")))
    return 0


if __name__=="__main__": raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
V5=HERE.parent/"mechanism-first-v5"
MAX=9223372036854775807

def digest(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def require(ok:bool,message:str):
    if not ok: raise SystemExit(f"V5.1 pre-build: NO-GO: {message}")

def main()->int:
    pointer_path=HERE/"V5_1_PREBUILD_CURRENT.json"; pointer=json.loads(pointer_path.read_text())
    ledger_path=HERE/pointer["json_file"]; amendment_path=HERE/pointer["amendment_file"]
    require(digest(ledger_path)==pointer["json_sha256"],"replacement ledger hash mismatch")
    require(digest(amendment_path)==pointer["amendment_sha256"],"inheritance amendment hash mismatch")
    require(digest(V5/"V5_PREBUILD_CURRENT.json")==pointer["inherits_pointer_sha256"],"inherited V5 pointer hash mismatch")
    v5_pointer=json.loads((V5/"V5_PREBUILD_CURRENT.json").read_text()); inherited_ledger=V5/v5_pointer["json_file"]
    require(digest(inherited_ledger)==pointer["inherits_ledger_sha256"]==v5_pointer["json_sha256"],"inherited V5 ledger hash mismatch")
    amendment=json.loads(amendment_path.read_text()); require(amendment["amends_ledger_sha256"]==pointer["json_sha256"],"amendment targets another ledger")
    auth=amendment["authoritative_inheritance"]
    require(auth["pointer_sha256"]==pointer["inherits_pointer_sha256"],"amendment pointer hash mismatch")
    require(auth["ledger_sha256"]==pointer["inherits_ledger_sha256"],"amendment ledger hash mismatch")
    ledger=json.loads(ledger_path.read_text()); require(ledger["status"]=="frozen_prebuild","ledger is not frozen")
    require(ledger["admission_review"]["decision"]=="GO","admission review is not GO")
    candidate=ledger["replacement_candidate"]; require(candidate["candidate_id"]==pointer["replacement_candidate_id"],"candidate mismatch")
    checks=candidate["checks"]; require(len(checks)==5,"replacement must have exactly five scored checks")
    ids=[item["id"] for item in checks]; require(len(set(ids))==5,"duplicate check IDs")
    require(candidate["target_check_id"] in ids,"target check missing")
    for item in checks:
        require(item["expected_mutant_failed_checks"]==[item["id"]],f"{item['id']} is not singleton-failing")
        require(set(item["expected_mutant_passed_checks"])==set(ids)-{item["id"]},f"{item['id']} sibling roster mismatch")
    controls={item["id"] for item in candidate["common_cache_controls"]}
    require(controls=={"cache_retains_allow_and_deny","cache_half_open_ttl","cache_invalid_input_atomicity"},"common controls mismatch")
    require(candidate["independent_near_miss"] and candidate["anti_duplication"],"near miss or anti-duplication missing")
    print("V5.1 replacement ledger: GO (hash-bound + semantic structure)")
    return 0

if __name__=="__main__": raise SystemExit(main())

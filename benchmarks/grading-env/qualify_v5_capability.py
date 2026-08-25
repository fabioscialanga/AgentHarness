from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from materialize_v5_crypto_mutants import materialize_mutant

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = Path(os.environ.get("V5_CAPABILITY_REFERENCE", ROOT / "benchmarks/grading-env/mechanism-first-v5/references/attenuated-capability-verifier")).resolve()
CHECKS = ("capability_attenuation", "capability_chain_signatures", "capability_request_match", "capability_time_intersection", "capability_depth")
PROBE_COUNTS = {"capability_attenuation": 5, "capability_chain_signatures": 7, "capability_request_match": 7, "capability_time_intersection": 8, "capability_depth": 6}
SECRETS = {"root": bytes.fromhex("11" * 32), "alice": bytes.fromhex("22" * 32), "bob": bytes.fromhex("33" * 32)}
SENTINEL = b"preserve capability report\n\x00"
PROBE_COUNTER = 0


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def base_caps() -> list[dict[str, Any]]:
    return [
        {"actions":["read","write"],"depth":0,"expires_at":"2035-01-01T00:00:00Z","id":"cap-root","issuer":"root","max_depth":3,"not_before":"2030-01-01T00:00:00Z","resource_prefix":"/api/","subject":"alice","tenant":"tenant-a"},
        {"actions":["read","write"],"depth":1,"expires_at":"2034-01-01T00:00:00Z","id":"cap-child","issuer":"alice","max_depth":2,"not_before":"2031-01-01T00:00:00Z","resource_prefix":"/api/docs/","subject":"bob","tenant":"tenant-a"},
    ]


def make_chain(caps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = deepcopy(caps or base_caps())
    links=[]
    for index, cap in enumerate(rows):
        if index:
            cap["parent_digest"] = hashlib.sha256(canonical(rows[index-1])).hexdigest()
        signer = cap["issuer"] if index == 0 else rows[index-1]["subject"]
        links.append({"capability":cap,"signature_hex":hmac.new(SECRETS[signer],canonical(cap),hashlib.sha256).hexdigest()})
    return {"links":links,"schema_version":1}


def request(**changes: Any) -> dict[str, Any]:
    value={"action":"read","path":"/api/docs/item-1","subject":"bob","tenant":"tenant-a"}; value.update(changes); return value


def keyring() -> dict[str, Any]:
    return {"keys":[{"delegator":name,"secret_hex":secret.hex()} for name,secret in sorted(SECRETS.items())],"schema_version":1}


def invoke(*, chain: dict[str, Any], req: dict[str, Any] | None = None, as_of: str="2032-01-01T00:00:00Z", mutant: str="", expect_success: bool, chain_raw: bytes | None=None) -> bool:
    global PROBE_COUNTER
    PROBE_COUNTER += 1
    req_value = req or request()
    for existing_output in ((True,) if expect_success else (True, False)):
        with tempfile.TemporaryDirectory(prefix="v5-capability-probe-") as td:
            root=Path(td); chain_path=root/"chain.json"; req_path=root/"request.json"; keys_path=root/"keyring.json"; output=root/"report.json"
            chain_path.write_bytes(chain_raw if chain_raw is not None else canonical(chain)); req_path.write_bytes(canonical(req_value)); keys_path.write_bytes(canonical(keyring()))
            if existing_output: output.write_bytes(SENTINEL)
            implementation=REFERENCE
            if mutant: implementation=materialize_mutant(REFERENCE,"attenuated-capability-verifier",mutant,root/"implementation")
            env=dict(os.environ); env["PYTHONPATH"]=str(implementation); env["PYTHONHASHSEED"]="47"; env.pop("AGENTHARNESS_MUTANT",None)
            done=subprocess.run([sys.executable,"-m","capability.verify","--chain",str(chain_path),"--request",str(req_path),"--keyring",str(keys_path),"--as-of",as_of,"--output",str(output)],cwd=root,env=env,capture_output=True,text=True,timeout=20,check=False)
            residue=[p for p in root.iterdir() if p.name.startswith(".report.json.")]
            if expect_success:
                expected={"action":req_value["action"],"allowed":True,"as_of":as_of,"capability_id":chain["links"][-1]["capability"]["id"],"path":req_value["path"],"subject":req_value["subject"],"tenant":req_value["tenant"]}
                passed=done.returncode==0 and not done.stdout and not done.stderr and output.read_bytes()==canonical(expected) and not residue
            else:
                boundary_ok=output.read_bytes()==SENTINEL if existing_output else not output.exists()
                passed=done.returncode!=0 and not done.stdout and len(done.stderr.splitlines())==1 and "Traceback" not in done.stderr and boundary_ok and not residue
            if not passed: return False
    return True


def happy(mutant: str) -> bool: return invoke(chain=make_chain(),mutant=mutant,expect_success=True)


def check_attenuation(mutant: str) -> bool:
    path=base_caps(); path[1]["resource_prefix"]="/"
    actions=base_caps(); actions[0]["actions"]=["read"]; actions[1]["actions"]=["read","write"]
    tenant=base_caps(); tenant[1]["tenant"]="tenant-b"
    sibling=base_caps(); sibling[1]["resource_prefix"]="/api2/"
    return all((happy(mutant),invoke(chain=make_chain(path),req=request(path="/elsewhere"),mutant=mutant,expect_success=False),invoke(chain=make_chain(actions),mutant=mutant,expect_success=False),invoke(chain=make_chain(tenant),req=request(tenant="tenant-b"),mutant=mutant,expect_success=False),invoke(chain=make_chain(sibling),req=request(path="/api2/item"),mutant=mutant,expect_success=False)))


def check_signatures(mutant: str) -> bool:
    root=make_chain(); root["links"][0]["signature_hex"]="00"*32
    leaf=make_chain(); leaf["links"][-1]["signature_hex"]="00"*32
    truncated=make_chain(); truncated["links"][0]["signature_hex"]="00"
    swapped=make_chain(); swapped["links"].reverse()
    unknown=make_chain(); unknown["links"][0]["capability"]["issuer"]="unknown"
    duplicate=canonical(make_chain()).replace(b'"schema_version":1',b'"schema_version":1,"schema_version":1')
    return all((happy(mutant),invoke(chain=root,mutant=mutant,expect_success=False),invoke(chain=leaf,mutant=mutant,expect_success=False),invoke(chain=truncated,mutant=mutant,expect_success=False),invoke(chain=swapped,mutant=mutant,expect_success=False),invoke(chain=unknown,mutant=mutant,expect_success=False),invoke(chain=make_chain(),chain_raw=duplicate,mutant=mutant,expect_success=False)))


def check_request(mutant: str) -> bool:
    return all((happy(mutant),invoke(chain=make_chain(),req=request(subject="mallory"),mutant=mutant,expect_success=False),invoke(chain=make_chain(),req=request(tenant="tenant-b"),mutant=mutant,expect_success=False),invoke(chain=make_chain(),req=request(action="delete"),mutant=mutant,expect_success=False),invoke(chain=make_chain(),req=request(path="/api/docs-evil/item"),mutant=mutant,expect_success=False),invoke(chain=make_chain(),req=request(path="/prefix/api/docs/item"),mutant=mutant,expect_success=False),invoke(chain=make_chain(),req=request(path="/api/docs"),mutant=mutant,expect_success=True)))


def check_time(mutant: str) -> bool:
    late=base_caps(); late[0]["expires_at"]="2033-01-01T00:00:00Z"; late[1]["expires_at"]="2034-01-01T00:00:00Z"
    early=base_caps(); early[0]["not_before"]="2031-06-01T00:00:00Z"; early[1]["not_before"]="2031-01-01T00:00:00Z"
    return all((happy(mutant),invoke(chain=make_chain(late),as_of="2033-06-01T00:00:00Z",mutant=mutant,expect_success=False),invoke(chain=make_chain(early),as_of="2031-03-01T00:00:00Z",mutant=mutant,expect_success=False),invoke(chain=make_chain(),as_of="2031-01-01T00:00:00Z",mutant=mutant,expect_success=True),invoke(chain=make_chain(),as_of="2030-12-31T23:59:59Z",mutant=mutant,expect_success=False),invoke(chain=make_chain(),as_of="2034-01-01T00:00:00Z",mutant=mutant,expect_success=False),invoke(chain=make_chain(),as_of="2033-12-31T23:59:59Z",mutant=mutant,expect_success=True),invoke(chain=make_chain(),as_of="2032-01-01T00:00:00",mutant=mutant,expect_success=False)))


def check_depth(mutant: str) -> bool:
    exhausted=base_caps(); exhausted[0]["max_depth"]=0
    skipped=base_caps(); skipped[1]["depth"]=2
    broaden=base_caps(); broaden[1]["max_depth"]=4
    nested=base_caps(); nested[0]["max_depth"]=3; nested[1]["max_depth"]=1; nested.append({"actions":["read"],"depth":2,"expires_at":"2033-01-01T00:00:00Z","id":"cap-grandchild","issuer":"bob","max_depth":1,"not_before":"2032-01-01T00:00:00Z","resource_prefix":"/api/docs/private/","subject":"carol","tenant":"tenant-a"})
    negative=base_caps(); negative[1]["max_depth"]=-1
    return all((happy(mutant),invoke(chain=make_chain(exhausted),mutant=mutant,expect_success=False),invoke(chain=make_chain(skipped),mutant=mutant,expect_success=False),invoke(chain=make_chain(broaden),mutant=mutant,expect_success=False),invoke(chain=make_chain(nested),req=request(subject="carol",path="/api/docs/private/item"),as_of="2032-06-01T00:00:00Z",mutant=mutant,expect_success=False),invoke(chain=make_chain(negative),mutant=mutant,expect_success=False)))

FUNCTIONS={"capability_attenuation":check_attenuation,"capability_chain_signatures":check_signatures,"capability_request_match":check_request,"capability_time_intersection":check_time,"capability_depth":check_depth}


def evaluate(mutant: str="") -> dict[str,Any]:
    global PROBE_COUNTER
    checks={}; executed={}
    for name in CHECKS:
        PROBE_COUNTER=0; functional=FUNCTIONS[name](mutant); executed[name]=PROBE_COUNTER; checks[name]=functional and PROBE_COUNTER==PROBE_COUNTS[name]
    return {"implementation":mutant or "reference","passed":[n for n,v in checks.items() if v],"failed":[n for n,v in checks.items() if not v],"checks":checks,"executed_probes":executed}


def main(argv: list[str] | None=None) -> int:
    global REFERENCE
    parser=argparse.ArgumentParser(); parser.add_argument("--workspace",type=Path); args=parser.parse_args(argv)
    if args.workspace:
        REFERENCE=args.workspace.resolve(); rows=[evaluate("")]; ok=rows[0]["failed"]==[]
    else:
        rows=[evaluate("")]+[evaluate(name) for name in CHECKS]; expected={"reference":[]}|{name:[name] for name in CHECKS}; ok=all(row["failed"]==expected[row["implementation"]] for row in rows)
    print(json.dumps({"ok":ok,"task_id":"attenuated-capability-verifier","matrix":rows,"probe_counts":PROBE_COUNTS,"total_probes_per_implementation":sum(PROBE_COUNTS.values()),"reference_runs":1,"mutant_runs":0 if args.workspace else 5,"target_model_calls":0,"efficacy_cells":0},indent=2,sort_keys=True)); return 0 if ok else 1


if __name__=="__main__": raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from materialize_v5_crypto_mutants import materialize_mutant

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = Path(os.environ.get("V5_FRAME_PARSER_REFERENCE", ROOT / "benchmarks/grading-env/mechanism-first-v5/references/length-prefixed-frame-parser")).resolve()
CHECKS = ("frame_split_prefix_payload", "frame_max_before_alloc", "frame_truncated_eof", "frame_zero_and_multiple", "frame_endianness")
PROBE_COUNTS = {"frame_split_prefix_payload": 8, "frame_max_before_alloc": 15, "frame_truncated_eof": 10, "frame_zero_and_multiple": 6, "frame_endianness": 5}
PROBE_COUNTER = 0


def canonical(value: Any) -> bytes:
    return (json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def stream(*payloads: bytes) -> bytes:
    return b"".join(len(payload).to_bytes(4, "big") + payload for payload in payloads)


def layouts(raw: bytes) -> list[list[bytes]]:
    return [
        [raw],
        [bytes([byte]) for byte in raw],
        [raw[:1], raw[1:]],
        [raw[:2], raw[2:4], raw[4:]],
        [raw[:3], raw[3:5], raw[5:]],
        [b"", raw[:4], b"", raw[4:6], raw[6:], b""],
        [raw[:5], raw[5:9], raw[9:]],
        [raw[:1], raw[1:3], raw[3:4], raw[4:8], raw[8:9], raw[9:]],
    ]


class Runner:
    def __init__(self, mutant: str):
        self.temp = tempfile.TemporaryDirectory(prefix="v5-frame-")
        self.root = Path(self.temp.name)
        self.impl = REFERENCE if not mutant else materialize_mutant(REFERENCE, "length-prefixed-frame-parser", mutant, self.root / "implementation")
    def close(self) -> None:
        self.temp.cleanup()
    def invoke(self, chunks: list[bytes] | str, maximum: str, *, expected: list[bytes] | None = None, code: str | None = None, existing: bool = False) -> bool:
        output = self.root / f"out-{os.urandom(4).hex()}.json"
        sentinel = b"preserve-existing\n"
        if existing:
            output.write_bytes(sentinel)
        encoded = chunks if isinstance(chunks, str) else json.dumps([chunk.hex() for chunk in chunks], separators=(",", ":"))
        carrier=encoded
        if len(encoded)>100000:
            input_path=self.root/f"chunks-{os.urandom(4).hex()}.json"; input_path.write_text(encoded,encoding="utf-8"); carrier=f"@{input_path}"
        run = subprocess.run([sys.executable, "-m", "frame_parser.parse", "--chunks", carrier, "--max-frame", maximum, "--output", str(output)], cwd=self.root, env={**os.environ, "PYTHONPATH": str(self.impl), "PYTHONHASHSEED": "83"}, capture_output=True, timeout=30)
        if expected is not None:
            wanted = canonical([item.hex() for item in expected])
            return run.returncode == 0 and not run.stdout and not run.stderr and output.is_file() and output.read_bytes() == wanted
        preserved = output.read_bytes() == sentinel if existing else not output.exists()
        return run.returncode != 0 and not run.stdout and run.stderr == f"frame_error:{code}\n".encode() and b"Traceback" not in run.stderr and preserved
    def symlink_output(self) -> bool:
        target=self.root/"external.txt"; target.write_bytes(b"external-sentinel\n"); output=self.root/"linked-output.json"; output.symlink_to(target)
        encoded=json.dumps([stream(b"").hex()]); run=subprocess.run([sys.executable,"-m","frame_parser.parse","--chunks",encoded,"--max-frame","8","--output",str(output)],cwd=self.root,env={**os.environ,"PYTHONPATH":str(self.impl)},capture_output=True,timeout=30)
        return run.returncode==0 and not run.stdout and not run.stderr and not output.is_symlink() and output.read_bytes()==canonical([""]) and target.read_bytes()==b"external-sentinel\n"
    def output_failure(self) -> bool:
        output=self.root/"output-directory"; output.mkdir(); encoded=json.dumps([stream(b"").hex()]); run=subprocess.run([sys.executable,"-m","frame_parser.parse","--chunks",encoded,"--max-frame","8","--output",str(output)],cwd=self.root,env={**os.environ,"PYTHONPATH":str(self.impl)},capture_output=True,timeout=30)
        return run.returncode!=0 and not run.stdout and run.stderr==b"frame_error:output_error\n" and output.is_dir() and not list(output.iterdir())


def check_split(mutant: str) -> bool:
    global PROBE_COUNTER
    runner = Runner(mutant)
    try:
        large=b"a"*65792; large_stream=stream(large); empty_stream=stream(b"")
        cases=[
            ([large_stream],[large]),
            ([bytes([byte]) for byte in empty_stream],[b""]),
            ([empty_stream[:1],empty_stream[1:]],[b""]),
            ([large_stream[:2],large_stream[2:]],[large]),
            ([large_stream[:3],large_stream[3:]],[large]),
            ([large_stream[:4],large_stream[4:5],large_stream[5:]],[large]),
            ([large_stream[:5],large_stream[5:17],large_stream[17:]],[large]),
            ([large_stream[:4],large_stream[4:100],large_stream[100:1000],large_stream[1000:]],[large]),
        ]
        answers = []
        for chunks,expected in cases:
            PROBE_COUNTER += 1
            answers.append(runner.invoke(chunks, "65792", expected=expected))
        return all(answers)
    finally:
        runner.close()


def check_max(mutant: str) -> bool:
    global PROBE_COUNTER
    runner = Runner(mutant)
    try:
        cases = [
            ([(65792).to_bytes(4, "big")], "65791", None, "oversize"),
            ([(65792).to_bytes(4, "big")], "0", None, "oversize"),
            ([stream(b"a" * 65792)], "65792", [b"a" * 65792], None),
            ([b""], "1048577", None, "invalid_input"),
            ([b""], "01", None, "invalid_input"),
            ('["AA"]', "4", None, "invalid_input"),
        ]
        answers=[]
        for chunks, maximum, expected, code in cases:
            PROBE_COUNTER += 1
            answers.append(runner.invoke(chunks, maximum, expected=expected, code=code, existing=code is not None and len(answers) % 2 == 0))
        for raw in ('{}','["0"]','["gg"]','[NaN]',f'@{runner.root / "missing.json"}'):
            PROBE_COUNTER+=1; answers.append(runner.invoke(raw,"4",code="invalid_input",existing=PROBE_COUNTER%2==0))
        invalid_utf=runner.root/"invalid-utf.json"; invalid_utf.write_bytes(b"[\xff]")
        PROBE_COUNTER+=1; answers.append(runner.invoke(f"@{invalid_utf}","4",code="invalid_input",existing=True))
        PROBE_COUNTER+=1; answers.append(runner.invoke([b"\x00"*(2*1024*1024+1)],"4",code="invalid_input",existing=False))
        PROBE_COUNTER+=1; answers.append(runner.symlink_output())
        PROBE_COUNTER+=1; answers.append(runner.output_failure())
        return all(answers)
    finally:
        runner.close()


def check_truncated(mutant: str) -> bool:
    global PROBE_COUNTER
    runner = Runner(mutant)
    try:
        raw = stream(b"a" * 65792)
        cuts = [b"", raw[:1], raw[:2], raw[:3], raw[:4], raw[:5], raw[:6], raw[:7], raw[:8], raw[:-1]]
        answers=[]
        for index, value in enumerate(cuts):
            PROBE_COUNTER += 1
            expected=[] if not value else None
            if expected is not None:
                answers.append(runner.invoke([value], "65792", expected=expected))
            else:
                answers.append(runner.invoke([value], "65792", code="truncated", existing=index % 2 == 0))
        return all(answers)
    finally:
        runner.close()


def check_zero(mutant: str) -> bool:
    global PROBE_COUNTER
    runner=Runner(mutant)
    try:
        large=b"a"*65792
        payload_sets=[(b"",),(b"",large),(large,b""),(b"",b"",large),(large,b"",large),(b"",b"",b"")]
        answers=[]
        for values in payload_sets:
            PROBE_COUNTER+=1; answers.append(runner.invoke([stream(*values)],"65792",expected=list(values)))
        return all(answers)
    finally: runner.close()


def check_endian(mutant: str) -> bool:
    global PROBE_COUNTER
    runner=Runner(mutant)
    try:
        cases=[(b"a",),(b"ab",),(bytes(range(3)),),(b"a",b"bc"),(b"d",b"e")]
        answers=[]
        for values in cases:
            PROBE_COUNTER+=1; answers.append(runner.invoke([stream(*values)],"64",expected=list(values)))
        return all(answers)
    finally: runner.close()


FUNCTIONS={"frame_split_prefix_payload":check_split,"frame_max_before_alloc":check_max,"frame_truncated_eof":check_truncated,"frame_zero_and_multiple":check_zero,"frame_endianness":check_endian}


def evaluate(mutant: str="") -> dict[str,Any]:
    global PROBE_COUNTER
    before=PROBE_COUNTER; passed=[]; failed=[]
    for name in CHECKS:
        start=PROBE_COUNTER
        try: ok=FUNCTIONS[name](mutant)
        except Exception: ok=False
        if PROBE_COUNTER-start != PROBE_COUNTS[name]: raise RuntimeError(f"probe mismatch {name}: {PROBE_COUNTER-start}")
        (passed if ok else failed).append(name)
    return {"executed_probes":dict(PROBE_COUNTS),"failed":failed,"implementation":mutant or "reference","passed":passed,"probe_invocations":PROBE_COUNTER-before}


def main(argv: list[str]|None=None) -> int:
    global REFERENCE
    parser=argparse.ArgumentParser(); parser.add_argument("--workspace",type=Path); args=parser.parse_args(argv)
    if args.workspace:
        REFERENCE=args.workspace.resolve(); rows=[evaluate()]; ok=not rows[0]["failed"]; mutant_runs=0
    else:
        rows=[evaluate()]+[evaluate(name) for name in CHECKS]+[evaluate("frame_split_prefix_near_miss")]
        expected={"reference":[]}|{name:[name] for name in CHECKS}|{"frame_split_prefix_near_miss":["frame_split_prefix_payload"]}
        ok=all(row["failed"]==expected[row["implementation"]] for row in rows); mutant_runs=len(CHECKS)+1
    payload={"efficacy_cells":0,"matrix":rows,"mutant_runs":mutant_runs,"ok":ok,"probe_counts":PROBE_COUNTS,"target_model_calls":0,"task_id":"length-prefixed-frame-parser","total_probes_per_implementation":sum(PROBE_COUNTS.values())}
    print(json.dumps(payload,sort_keys=True,separators=(",",":")))
    return 0 if ok else 1


if __name__=="__main__": raise SystemExit(main())

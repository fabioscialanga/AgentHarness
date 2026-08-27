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

ROOT=Path(__file__).resolve().parents[2]
REFERENCE=Path(os.environ.get("V5_CSV_STREAM_REFERENCE",ROOT/"benchmarks/grading-env/mechanism-first-v5/references/streaming-csv-quoted-records")).resolve()
CHECKS=("csv_quoted_chunk_state","csv_header_exact","csv_row_width","csv_field_limit","csv_strict_eof")
PROBE_COUNTS={"csv_quoted_chunk_state":10,"csv_header_exact":17,"csv_row_width":8,"csv_field_limit":8,"csv_strict_eof":10}
PROBE_COUNTER=0


def canonical(value: Any) -> bytes:
    return (json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n").encode()


class Runner:
    def __init__(self,mutant: str):
        self.temp=tempfile.TemporaryDirectory(prefix="v5-csv-"); self.root=Path(self.temp.name); self.impl=self.root/"impl"
        materialize_mutant(REFERENCE,"streaming-csv-quoted-records",mutant,self.impl) if mutant else __import__("shutil").copytree(REFERENCE,self.impl)
    def close(self): self.temp.cleanup()
    def invoke(self,chunks: list[bytes] | str,maximum: str,expected: Any=None,code: str|None=None,existing: bool=False) -> bool:
        output=self.root/f"out-{os.urandom(4).hex()}.json"; sentinel=b"do-not-replace\n"
        if existing: output.write_bytes(sentinel)
        encoded=chunks if isinstance(chunks,str) else json.dumps([chunk.hex() for chunk in chunks],separators=(",",":"))
        carrier=encoded
        if len(encoded)>100000:
            source=self.root/f"chunks-{os.urandom(4).hex()}.json"; source.write_text(encoded,encoding="utf-8"); carrier=f"@{source}"
        run=subprocess.run([sys.executable,"-m","csv_stream.parse","--chunks",carrier,"--max-field-bytes",maximum,"--output",str(output)],cwd=self.root,env={**os.environ,"PYTHONPATH":str(self.impl),"PYTHONHASHSEED":"89"},capture_output=True,timeout=30)
        if code is None:
            return run.returncode==0 and not run.stdout and not run.stderr and output.is_file() and output.read_bytes()==canonical(expected)
        preserved=output.read_bytes()==sentinel if existing else not output.exists()
        return run.returncode!=0 and not run.stdout and run.stderr==f"csv_error:{code}\n".encode() and b"Traceback" not in run.stderr and preserved
    def symlink_output(self) -> bool:
        target=self.root/"external"; target.write_bytes(b"external\n"); output=self.root/"linked"; output.symlink_to(target)
        raw=b"id,name,value\r\n"; encoded=json.dumps([raw.hex()]); run=subprocess.run([sys.executable,"-m","csv_stream.parse","--chunks",encoded,"--max-field-bytes","5","--output",str(output)],cwd=self.root,env={**os.environ,"PYTHONPATH":str(self.impl)},capture_output=True,timeout=30)
        return run.returncode==0 and not run.stdout and not run.stderr and not output.is_symlink() and output.read_bytes()==b"[]\n" and target.read_bytes()==b"external\n"
    def output_failure(self) -> bool:
        output=self.root/"directory"; output.mkdir(); raw=b"id,name,value\r\n"; encoded=json.dumps([raw.hex()]); run=subprocess.run([sys.executable,"-m","csv_stream.parse","--chunks",encoded,"--max-field-bytes","5","--output",str(output)],cwd=self.root,env={**os.environ,"PYTHONPATH":str(self.impl)},capture_output=True,timeout=30)
        return run.returncode!=0 and not run.stdout and run.stderr==b"csv_error:output_error\n" and output.is_dir() and not list(output.iterdir())
    def invalid_argv(self, extra: list[str]) -> bool:
        run=subprocess.run([sys.executable,"-m","csv_stream.parse",*extra],cwd=self.root,env={**os.environ,"PYTHONPATH":str(self.impl)},capture_output=True,timeout=30)
        return run.returncode!=0 and not run.stdout and run.stderr==b"csv_error:invalid_input\n"
    def bounded_output(self) -> bool:
        import resource
        record=b"1,A,x\r\n"; count=((2*1024*1024)-len(HEADER))//len(record); raw=HEADER+record*count
        source=self.root/"bounded.json"; source.write_text(json.dumps([raw.hex()],separators=(",",":")),encoding="utf-8")
        output=self.root/"bounded-output.json"
        def limit_memory() -> None:
            ceiling=80*1024*1024
            resource.setrlimit(resource.RLIMIT_AS,(ceiling,ceiling))
        run=subprocess.run([sys.executable,"-m","csv_stream.parse","--chunks",f"@{source}","--max-field-bytes","5","--output",str(output)],cwd=self.root,env={**os.environ,"PYTHONPATH":str(self.impl),"PYTHONHASHSEED":"89"},capture_output=True,timeout=60,preexec_fn=limit_memory)
        item=canonical(row("1","A","x"))[:-1]; expected_size=count*(len(item)+1)+2
        if run.returncode!=0 or run.stdout or run.stderr or not output.is_file() or output.stat().st_size!=expected_size:
            return False
        with output.open("rb") as handle:
            first=handle.read(1); handle.seek(-2,os.SEEK_END); last=handle.read()
        return first==b"[" and last==b"]\n"


def row(identifier: str,name: str,value: str) -> dict[str,str]: return {"id":identifier,"name":name,"value":value}
HEADER=b"id,name,value\r\n"


def check_quoted(mutant: str) -> bool:
    global PROBE_COUNTER
    r=Runner(mutant)
    try:
        raw=HEADER+b'1,"Ada, A.","line1\r\nline2 and ""quote"""\r\n'
        expected=[row("1","Ada, A.",'line1\r\nline2 and "quote"')]
        points=[0,1,raw.index(b'"'),raw.index(b'line1')+2,raw.index(b'\r\nline2')+1,raw.index(b'""quote')+1,raw.index(b'""quote')+2,len(raw)-3,len(raw)-1]
        cases=[[raw],[bytes([byte]) for byte in raw]]
        for point in points:
            if point: cases.append([raw[:point],raw[point:]])
        answers=[]
        for chunks in cases[:10]: PROBE_COUNTER+=1; answers.append(r.invoke(chunks,"64",expected))
        return all(answers)
    finally:r.close()


def check_header(mutant: str) -> bool:
    global PROBE_COUNTER
    r=Runner(mutant)
    try:
        cases=[
            (b"name,id,value\r\nAda,1,x\r\n","header"),(b"id,name,id\r\n1,A,x\r\n","header"),(b"id,name\r\n1,A\r\n","header"),(b"id,name,value,extra\r\n1,A,x,y\r\n","header"),(b'"id",name,value\r\n1,A,x\r\n',"header"),(HEADER,None),
        ]
        answers=[]
        for index,(raw,code) in enumerate(cases):
            PROBE_COUNTER+=1; answers.append(r.invoke([raw],"5",[] if code is None else None,code,index%2==0 and code is not None))
        invalid=['{}','["0"]','["GG"]','[NaN]',f'@{r.root/"missing"}']
        for text in invalid: PROBE_COUNTER+=1; answers.append(r.invoke(text,"5",code="invalid_input",existing=PROBE_COUNTER%2==0))
        bad=r.root/"bad.json"; bad.write_bytes(b"[\xff]"); PROBE_COUNTER+=1; answers.append(r.invoke(f"@{bad}","5",code="invalid_input",existing=True))
        PROBE_COUNTER+=1; answers.append(r.invoke([b"x"*(2*1024*1024+1)],"5",code="invalid_input"))
        PROBE_COUNTER+=1; answers.append(r.symlink_output())
        PROBE_COUNTER+=1; answers.append(r.output_failure())
        PROBE_COUNTER+=1; answers.append(r.invalid_argv(["--chunks","[]","--max-field-bytes","5"]))
        PROBE_COUNTER+=1; answers.append(r.invalid_argv(["--chunks","[]","--max-field-bytes","5","--output",str(r.root/"unused"),"--unknown"]))
        return all(answers)
    finally:r.close()


def check_width(mutant: str) -> bool:
    global PROBE_COUNTER
    r=Runner(mutant)
    try:
        cases=[
            (HEADER+b"1,A,\r\n",[row("1","A","")],None),(HEADER+b"1,A\r\n",None,"row_width"),(HEADER+b"1,A,x,y\r\n",None,"row_width"),(HEADER+b"1,,\r\n",[row("1","","")],None),(HEADER+b",,\r\n",[row("","","")],None),(HEADER+b"1,A,x\r\n2,B,y\r\n",[row("1","A","x"),row("2","B","y")],None),(HEADER+b"1,A,x,\r\n",None,"row_width")]
        answers=[]
        for index,(raw,expected,code) in enumerate(cases): PROBE_COUNTER+=1; answers.append(r.invoke([raw],"5",expected,code,index%2==1))
        PROBE_COUNTER+=1; answers.append(r.bounded_output())
        return all(answers)
    finally:r.close()


def check_limit(mutant: str) -> bool:
    global PROBE_COUNTER
    r=Runner(mutant)
    try:
        cases=[
            (HEADER+b'1,A,"123456',"5",None,"field_limit"),(HEADER+b'1,A,"12345"\r\n',"5",[row("1","A","12345")],None),(HEADER+b"1,A,123456\r\n","5",None,"field_limit"),(HEADER+b'1,A,"12""34"\r\n',"5",[row("1","A",'12"34')],None),(HEADER+b'1,A,"\xc3\xa9\xc3\xa9\xc3\xa9"\r\n',"5",None,"field_limit"),(HEADER+b'1,A,"\xc3\xa9\xc3\xa9"\r\n',"5",[row("1","A","éé")],None),(HEADER+b"1,A,\xff\r\n","5",None,"invalid_input"),(HEADER,"01",None,"invalid_input")]
        answers=[]
        for index,(raw,maximum,expected,code) in enumerate(cases): PROBE_COUNTER+=1; answers.append(r.invoke([raw],maximum,expected,code,index%2==0 and code is not None))
        return all(answers)
    finally:r.close()


def check_eof(mutant: str) -> bool:
    global PROBE_COUNTER
    r=Runner(mutant)
    try:
        cases=[
            (HEADER+b'1,A,"abc',"strict_eof"),(HEADER+b"1,A,x\r","strict_eof"),(HEADER+b"1,A,x","strict_eof"),(HEADER+b'1,A,"abc"',"strict_eof"),(b"id,name,value\r","strict_eof"),(HEADER+b"1,A,x\n","invalid_input"),(HEADER+b"1,A,x\rX","strict_eof"),(b"","header"),(HEADER+b'1,A,"',"strict_eof"),(HEADER+b"1,A,\xc3\r\n","invalid_input")]
        answers=[]
        for index,(raw,code) in enumerate(cases): PROBE_COUNTER+=1; answers.append(r.invoke([raw],"16",code=code,existing=index%2==0))
        return all(answers)
    finally:r.close()

FUNCTIONS={"csv_quoted_chunk_state":check_quoted,"csv_header_exact":check_header,"csv_row_width":check_width,"csv_field_limit":check_limit,"csv_strict_eof":check_eof}


def evaluate(mutant: str="") -> dict[str,Any]:
    global PROBE_COUNTER
    start=PROBE_COUNTER; checks={}
    for name in CHECKS:
        before=PROBE_COUNTER
        try: checks[name]=FUNCTIONS[name](mutant)
        except Exception: checks[name]=False
        if PROBE_COUNTER-before!=PROBE_COUNTS[name]: raise RuntimeError(f"probe mismatch {name}: {PROBE_COUNTER-before}")
    return {"checks":checks,"executed_probes":dict(PROBE_COUNTS),"failed":[name for name in CHECKS if not checks[name]],"implementation":mutant or "reference","passed":[name for name in CHECKS if checks[name]]}


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--workspace",type=Path); args=parser.parse_args()
    if args.workspace:
        global REFERENCE; REFERENCE=args.workspace.resolve(); rows=[evaluate()]; ok=not rows[0]["failed"]
    else:
        rows=[evaluate()]+[evaluate(name) for name in CHECKS]+[evaluate("csv_quoted_escape_near_miss")]
        expected={"reference":[]}|{name:[name] for name in CHECKS}|{"csv_quoted_escape_near_miss":["csv_quoted_chunk_state"]}; ok=all(row["failed"]==expected[row["implementation"]] for row in rows)
    payload={"efficacy_cells":0,"matrix":rows,"mutant_runs":0 if args.workspace else len(CHECKS)+1,"ok":ok,"probe_counts":PROBE_COUNTS,"target_model_calls":0,"task_id":"streaming-csv-quoted-records","total_probes_per_implementation":sum(PROBE_COUNTS.values())}
    print(json.dumps(payload,sort_keys=True,separators=(",",":"))); return 0 if ok else 1


if __name__=="__main__": raise SystemExit(main())

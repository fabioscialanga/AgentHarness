from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

MUTANT=os.getenv("AGENTHARNESS_MUTANT","")

def validate_name(name:str)->str:
    if MUTANT=="archive_path_containment_atomic" and ".." in PurePosixPath(name).parts: return name
    if "\x00" in name or "\\" in name or name.startswith("/"): raise ValueError("unsafe path")
    if len(name)>=2 and name[1]==":": raise ValueError("drive path")
    parts=PurePosixPath(name).parts
    if not parts or any(p in {"..",""} for p in parts): raise ValueError("unsafe path")
    normalized="/".join(p for p in parts if p!=".")
    if not normalized: raise ValueError("empty path")
    return normalized

def main()->int:
    parser=argparse.ArgumentParser(); parser.add_argument("--archive",required=True); parser.add_argument("--out-dir",required=True); parser.add_argument("--max-entries",type=int,required=True); parser.add_argument("--max-bytes",type=int,required=True); args=parser.parse_args()
    out=Path(args.out_dir); stage=None
    try:
        if args.max_entries<=0 or args.max_bytes<=0: raise ValueError("limits must be positive")
        if out.exists(): raise ValueError("out-dir already exists")
        with zipfile.ZipFile(args.archive) as archive:
            infos=archive.infolist(); rows=[]; names=[]
            for info in infos:
                name=validate_name(info.filename); names.append((name,info))
                mode=(info.external_attr>>16)&0xFFFF
                kind=stat.S_IFMT(mode)
                is_dir=info.is_dir() or name.endswith("/")
                if MUTANT!="archive_special_entry_rejection" and kind not in {0,stat.S_IFREG,stat.S_IFDIR}: raise ValueError("special entry")
                if not is_dir: rows.append((name,info))
            normalized=[name.rstrip("/") for name,_ in names]
            collision=len(normalized)!=len(set(normalized)) or any(a!=b and (a.startswith(b+"/") or b.startswith(a+"/")) and not next(i for n,i in names if n.rstrip("/")==min(a,b,key=len)).is_dir() for a in normalized for b in normalized)
            if collision and MUTANT!="archive_collision_atomic": raise ValueError("path collision")
            if collision and MUTANT=="archive_collision_atomic":
                rows=[(n,i) for n,i in rows if not any(other!=n and other.startswith(n+"/") for other,_ in rows)]
                names=[(n,i) for n,i in names if i.is_dir() or any(n==rn for rn,_ in rows)]
            if MUTANT!="archive_limits_corruption_atomic" and (len(rows)>args.max_entries or sum(i.file_size for _,i in rows)>args.max_bytes): raise ValueError("limit exceeded")
            stage=Path(tempfile.mkdtemp(prefix=".extract-",dir=out.parent))
            files=[]
            for name,info in names:
                target=stage/name
                if info.is_dir() or name.endswith("/"): target.mkdir(parents=True,exist_ok=True); continue
                target.parent.mkdir(parents=True,exist_ok=True); data=archive.read(info); target.write_bytes(data)
                files.append({"path":name,"size":len(data),"sha256":hashlib.sha256(data).hexdigest()})
            files.sort(key=lambda x:x["path"])
            if MUTANT=="archive_extract_manifest" and files: files[0]["sha256"]="0"*64
            manifest={"files":files,"file_count":len(files),"total_bytes":sum(x["size"] for x in files)}
            (stage/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
        stage.replace(out); stage=None; return 0
    except Exception as exc:
        if stage is not None: shutil.rmtree(stage,ignore_errors=True)
        print(str(exc),file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())

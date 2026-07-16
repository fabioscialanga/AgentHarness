from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import Integer, String, Text, UniqueConstraint, create_engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

MUTANT=os.getenv("AGENTHARNESS_MUTANT","")
DB=Path(__file__).resolve().parents[1]/"documents.db"
engine=create_engine(f"sqlite:///{DB}",connect_args={"check_same_thread":False})

class Base(DeclarativeBase): pass
class Document(Base):
    __tablename__="documents"; document_id:Mapped[str]=mapped_column(String,primary_key=True); revision:Mapped[int]=mapped_column(Integer); body:Mapped[str]=mapped_column(Text)
class Revision(Base):
    __tablename__="revisions"; __table_args__=(UniqueConstraint("document_id","revision"),); row_id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True); document_id:Mapped[str]=mapped_column(String,index=True); revision:Mapped[int]=mapped_column(Integer); body:Mapped[str]=mapped_column(Text)
Base.metadata.create_all(engine)
app=FastAPI()

class CreateBody(BaseModel): document:dict[str,Any]

def etag(revision:int)->str: return f'"v{revision}"'
def payload(item:Document)->dict[str,Any]: return {"document_id":item.document_id,"revision":item.revision,"document":json.loads(item.body)}
def merge(target:Any,patch:Any)->Any:
    if not isinstance(patch,dict): return deepcopy(patch)
    result=deepcopy(target) if isinstance(target,dict) else {}
    for key,value in patch.items():
        if value is None: result.pop(key,None)
        else: result[key]=merge(result.get(key),value)
    return result

def require_match(item:Document,value:str|None)->None:
    if value is None: raise HTTPException(428,"If-Match required")
    if value!=etag(item.revision): raise HTTPException(412,"stale")

def cas_commit(session:Session,item:Document,expected:int,new_body:str)->Document:
    changed=session.execute(
        update(Document)
        .where(Document.document_id==item.document_id,Document.revision==expected)
        .values(revision=expected+1,body=new_body)
        .execution_options(synchronize_session=False)
    )
    if getattr(changed,"rowcount",0)!=1:
        session.rollback(); raise HTTPException(412,"stale")
    session.add(Revision(document_id=item.document_id,revision=expected+1,body=new_body))
    try: session.commit()
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(412,"stale") from exc
    current=session.get(Document,item.document_id)
    if current is None: raise HTTPException(500,"document disappeared")
    return current

@app.post("/documents",status_code=201)
def create(body:CreateBody,response:Response):
    with Session(engine) as session:
        item=Document(document_id=str(uuid.uuid4()),revision=1,body=json.dumps(body.document,sort_keys=True))
        session.add(item); session.add(Revision(document_id=item.document_id,revision=1,body=item.body))
        response.headers["ETag"]=etag(1)
        if MUTANT=="document_create_etag_persistence" and os.getenv("AGENTHARNESS_CROSS_PROCESS_CHILD")=="1":
            session.flush(); result=payload(item); session.rollback(); return result
        session.commit(); return payload(item)

@app.get("/documents/{document_id}")
def get_document(document_id:str,response:Response):
    with Session(engine) as session:
        item=session.get(Document,document_id)
        if not item: raise HTTPException(404,"not found")
        response.headers["ETag"]=etag(item.revision); return payload(item)

@app.patch("/documents/{document_id}")
def patch_document(document_id:str,patch:dict[str,Any],response:Response,if_match:str|None=Header(None,alias="If-Match")):
    with Session(engine) as session:
        item=session.get(Document,document_id)
        if not item: raise HTTPException(404,"not found")
        if MUTANT=="document_if_match_atomic" and if_match is not None and if_match!=etag(item.revision):
            response.headers["ETag"]=etag(item.revision); return payload(item)
        require_match(item,if_match)
        current=json.loads(item.body)
        updated={**current,**patch} if MUTANT=="document_merge_patch" else merge(current,patch)
        item=cas_commit(session,item,item.revision,json.dumps(updated,sort_keys=True))
        response.headers["ETag"]=etag(item.revision); return payload(item)

@app.get("/documents/{document_id}/revisions")
def revisions(document_id:str):
    with Session(engine) as session:
        if not session.get(Document,document_id): raise HTTPException(404,"not found")
        rows=list(session.scalars(select(Revision).where(Revision.document_id==document_id).order_by(Revision.revision)))
        result=[{"revision":r.revision,"document":json.loads(r.body)} for r in rows]
        return list(reversed(result)) if MUTANT=="document_revision_history" else result

@app.post("/documents/{document_id}/restore/{revision}")
def restore(document_id:str,revision:int,response:Response,if_match:str|None=Header(None,alias="If-Match")):
    with Session(engine) as session:
        item=session.get(Document,document_id)
        if not item: raise HTTPException(404,"not found")
        require_match(item,if_match)
        old=session.scalar(select(Revision).where(Revision.document_id==document_id,Revision.revision==revision))
        if not old: raise HTTPException(404,"revision not found")
        if MUTANT=="document_restore_history":
            item.body=old.body; session.commit()
        else:
            item=cas_commit(session,item,item.revision,old.body)
        response.headers["ETag"]=etag(item.revision); return payload(item)

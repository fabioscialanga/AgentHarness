from __future__ import annotations

import os
import re
from typing import Any

from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse

from .interfaces import PolicySnapshot

ID=re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MAX=9223372036854775807
MUTANT=os.environ.get("AGENTHARNESS_MUTANT", "")

def integer(value:Any)->bool: return isinstance(value,int) and not isinstance(value,bool) and 1<=value<=MAX
def invalid(): return JSONResponse({"detail":"invalid_request"},status_code=422)

def create_app(policy_store,clock,ttl_seconds=60):
    if not isinstance(ttl_seconds,int) or isinstance(ttl_seconds,bool) or not 1<=ttl_seconds<=3600: raise ValueError("invalid ttl_seconds")
    app=FastAPI(); entries={}
    def key(tenant,subject,resource,action,revision):
        if MUTANT=="auth_cache_resource_identity": return (tenant,subject,action,revision)
        if MUTANT=="auth_cache_tenant": return (subject,resource,action,revision)
        if MUTANT=="auth_cache_subject": return (tenant,resource,action,revision)
        if MUTANT=="auth_cache_action": return (tenant,subject,resource,revision)
        if MUTANT=="auth_cache_policy_revision": return (tenant,subject,resource,action)
        if MUTANT=="auth_cache_resource_alias_near_miss": resource=resource.split(".",1)[0]
        return (tenant,subject,resource,action,revision)
    @app.post("/authorize")
    async def authorize(request:Request):
        try: body=await request.json()
        except Exception: return invalid()
        if not isinstance(body,dict) or set(body)!={"tenant","subject","resource_id","action"}: return invalid()
        tenant=body["tenant"]; subject=body["subject"]; resource=body["resource_id"]; action=body["action"]
        if any(not isinstance(x,str) or ID.fullmatch(x) is None for x in (tenant,subject,resource,action)): return invalid()
        try: snapshot=policy_store.snapshot(tenant,subject)
        except Exception: return invalid()
        if type(snapshot) is not PolicySnapshot or not integer(snapshot.revision) or snapshot.evaluation_token is None: return invalid()
        try: now=clock.now()
        except Exception: return invalid()
        if not integer(now): return invalid()
        cache_key=key(tenant,subject,resource,action,snapshot.revision); old=entries.get(cache_key)
        if old is not None and now-old[1] < ttl_seconds:
            return {"allowed":old[0],"policy_revision":snapshot.revision,"cache":"hit"}
        try: allowed=policy_store.evaluate(snapshot,resource,action)
        except Exception: return invalid()
        if type(allowed) is not bool: return invalid()
        entries[cache_key]=(allowed,now)
        return {"allowed":allowed,"policy_revision":snapshot.revision,"cache":"miss"}
    return app

"""API: Prometheus-Endpunkt (Token je Profil) und Grafana-Dashboard."""
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from . import prometheus
from .auth import client_ip, profile_access, rate_limit, require_user
from .db import audit, db

router = APIRouter(prefix="/api/profiles/{pid}/prometheus")


@router.get("")
def scrape(pid: int, request: Request):
    """Für Prometheus: Authorization: Bearer <token>. Kein Sitzungs-Login nötig."""
    with db() as c:
        if not prometheus.check(c, pid, request.headers.get("authorization")):
            rate_limit(f"prom:{client_ip(request)}", 30)  # zählt nur Fehlversuche
            raise HTTPException(401, "Token fehlt oder ist ungültig")
        text = prometheus.render(c, pid)
    return Response(text, media_type="text/plain; version=0.0.4; charset=utf-8", headers={"Cache-Control": "no-store"})


@router.get("/settings")
def settings(pid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid)
        return prometheus.info(c, pid)


@router.post("/token")
def token(pid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "owner")
        tok = prometheus.new_token(c, pid)
        audit(c, "prometheus.token", user["id"], pid)
        return dict(prometheus.info(c, pid), token=tok)


@router.delete("/token")
def revoke(pid: int, user=Depends(require_user)):
    with db() as c:
        profile_access(c, user, pid, "owner")
        prometheus.revoke(c, pid)
        audit(c, "prometheus.revoke", user["id"], pid)
        return prometheus.info(c, pid)


@router.get("/grafana.json")
def grafana(pid: int, user=Depends(require_user)):
    with db() as c:
        p, _ = profile_access(c, user, pid)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", p["name"]).strip("_") or "profil"
    return Response(json.dumps(prometheus.grafana_dashboard(p["name"]), ensure_ascii=False, indent=1), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="diktyo-grafana-{name}.json"'})

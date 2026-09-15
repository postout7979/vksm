import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.agent_auth import extract_bearer, new_token
from app.agent_sim import AGENT_VERSION, simulate_heartbeat
from app.database import get_db

router = APIRouter(prefix="/api/supervisors", tags=["supervisors"])


@router.get("", response_model=List[schemas.SupervisorOut])
def list_supervisors(db: Session = Depends(get_db)):
    return db.query(models.SupervisorCluster).all()


@router.post("", response_model=schemas.SupervisorOut, status_code=201)
def register_supervisor(body: schemas.SupervisorCreate, db: Session = Depends(get_db)):
    existing = (
        db.query(models.SupervisorCluster)
        .filter(models.SupervisorCluster.name == body.name)
        .first()
    )
    if existing:
        raise HTTPException(409, "Supervisor with this name is already registered")

    sup = models.SupervisorCluster(name=body.name, vcf_instance=body.vcf_instance)
    db.add(sup)
    db.commit()
    db.refresh(sup)
    return sup


def _get_supervisor_or_404(db: Session, supervisor_id: int) -> models.SupervisorCluster:
    sup = db.get(models.SupervisorCluster, supervisor_id)
    if not sup:
        raise HTTPException(404, "Supervisor not found")
    return sup


@router.post("/{supervisor_id}/deploy-agent", response_model=schemas.SupervisorOut)
def deploy_agent_pod(supervisor_id: int, db: Session = Depends(get_db)):
    """Simulate deploying the portal's agent pod onto the Supervisor
    cluster. In a real environment this would apply a Deployment
    manifest to the Supervisor via its Kubernetes API."""
    sup = _get_supervisor_or_404(db, supervisor_id)
    sup.agent_status = models.SupervisorAgentStatus.RUNNING
    sup.agent_version = AGENT_VERSION
    db.commit()
    db.refresh(sup)
    return sup


@router.post("/{supervisor_id}/register-secret", response_model=schemas.SupervisorOut)
def register_secret(
    supervisor_id: int,
    body: schemas.SecretRegisterRequest,
    db: Session = Depends(get_db),
):
    """Register the Secret created by the agent pod with the portal,
    then open a persistent session (mirrors the flow described for
    the VCF 9.1 Supervisor agent: agent pod creates a Secret -> portal
    registers it -> session is kept alive with heartbeats)."""
    sup = _get_supervisor_or_404(db, supervisor_id)
    if sup.agent_status != models.SupervisorAgentStatus.RUNNING:
        raise HTTPException(400, "Agent pod must be running before registering its secret")

    sup.secret_registered = True
    sup.secret_name = body.secret_name
    sup.session_status = models.SessionStatus.CONNECTED
    sup.last_heartbeat = simulate_heartbeat()
    db.commit()
    db.refresh(sup)
    return sup


@router.post("/{supervisor_id}/heartbeat", response_model=schemas.SupervisorOut)
def heartbeat(supervisor_id: int, db: Session = Depends(get_db)):
    """Called periodically by the agent pod (simulated here) to keep
    the session alive and report the Supervisor is still reachable."""
    sup = _get_supervisor_or_404(db, supervisor_id)
    if not sup.secret_registered:
        raise HTTPException(400, "No session established: secret not registered")
    sup.session_status = models.SessionStatus.CONNECTED
    sup.last_heartbeat = simulate_heartbeat()
    db.commit()
    db.refresh(sup)
    return sup


@router.delete("/{supervisor_id}", status_code=204)
def delete_supervisor(supervisor_id: int, db: Session = Depends(get_db)):
    sup = _get_supervisor_or_404(db, supervisor_id)
    db.delete(sup)
    db.commit()


# ---------------------------------------------------------------------
# Real agent integration surface.
#
# The endpoints above (deploy-agent / register-secret / heartbeat) are
# used by the demo dashboard to simulate a Supervisor without needing a
# real VCF environment. The endpoints below are what an actual agent
# pod, deployed via the supervisor-agent.yaml manifest, talks to. They
# are authenticated with a bootstrap token (embedded once in the
# deployment's Secret) followed by a long-lived session token that the
# agent itself generates.
# ---------------------------------------------------------------------


@router.post("/{supervisor_id}/agent/bootstrap", response_model=schemas.BootstrapTokenOut)
def issue_bootstrap_token(supervisor_id: int, db: Session = Depends(get_db)):
    """Admin-initiated: mint a short-lived token to embed in the
    Secret shipped with supervisor-agent.yaml before applying it."""
    sup = _get_supervisor_or_404(db, supervisor_id)
    sup.bootstrap_token = new_token()
    sup.agent_status = models.SupervisorAgentStatus.DEPLOYING
    db.commit()
    return schemas.BootstrapTokenOut(bootstrap_token=sup.bootstrap_token)


@router.post("/{supervisor_id}/agent/register", response_model=schemas.SupervisorOut)
def agent_register(
    supervisor_id: int,
    body: schemas.SupervisorAgentRegisterRequest,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Agent-initiated: exchange the one-time bootstrap token for a
    registered session. The agent has already created its own
    Kubernetes Secret (body.secret_name) holding body.secret_token;
    from here on that token authenticates heartbeat/status calls."""
    sup = _get_supervisor_or_404(db, supervisor_id)
    token = extract_bearer(authorization)
    if not sup.bootstrap_token or token != sup.bootstrap_token:
        raise HTTPException(401, "Invalid or expired bootstrap token")

    sup.secret_name = body.secret_name
    sup.secret_token = body.secret_token
    sup.secret_registered = True
    sup.agent_status = models.SupervisorAgentStatus.RUNNING
    sup.agent_version = AGENT_VERSION
    sup.session_status = models.SessionStatus.CONNECTED
    sup.last_heartbeat = datetime.utcnow()
    sup.bootstrap_token = None
    db.commit()
    db.refresh(sup)
    return sup


def _require_session(sup: models.SupervisorCluster, authorization: Optional[str]) -> None:
    token = extract_bearer(authorization)
    if not sup.secret_token or token != sup.secret_token:
        raise HTTPException(401, "Invalid session token")


@router.post("/{supervisor_id}/agent/heartbeat", response_model=schemas.SupervisorOut)
def agent_heartbeat(
    supervisor_id: int,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    sup = _get_supervisor_or_404(db, supervisor_id)
    _require_session(sup, authorization)
    sup.session_status = models.SessionStatus.CONNECTED
    sup.last_heartbeat = datetime.utcnow()
    db.commit()
    db.refresh(sup)
    return sup


@router.post("/{supervisor_id}/agent/status")
def agent_status_report(
    supervisor_id: int,
    body: schemas.SupervisorStatusReportRequest,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Agent-initiated: push the operational status it collected
    from the Supervisor cluster (node counts, capacity, health, ...)."""
    sup = _get_supervisor_or_404(db, supervisor_id)
    _require_session(sup, authorization)
    sup.status_json = json.dumps(body.data)
    sup.session_status = models.SessionStatus.CONNECTED
    sup.last_heartbeat = datetime.utcnow()
    db.commit()
    return {"status": "ok"}


@router.get("/{supervisor_id}/status")
def get_status(supervisor_id: int, db: Session = Depends(get_db)):
    sup = _get_supervisor_or_404(db, supervisor_id)
    return json.loads(sup.status_json) if sup.status_json else {}

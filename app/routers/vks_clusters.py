import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.agent_auth import extract_bearer, new_token
from app.agent_sim import AGENT_VERSION, build_inventory, simulate_heartbeat
from app.database import get_db

router = APIRouter(prefix="/api/vks-clusters", tags=["vks-clusters"])


def _get_cluster_or_404(db: Session, cluster_id: int) -> models.VksCluster:
    cluster = db.get(models.VksCluster, cluster_id)
    if not cluster:
        raise HTTPException(404, "VKS cluster not found")
    return cluster


def _to_detail(cluster: models.VksCluster) -> schemas.VksClusterDetail:
    data = schemas.VksClusterOut.model_validate(cluster).model_dump()
    data["inventory"] = json.loads(cluster.inventory_json) if cluster.inventory_json else None
    return schemas.VksClusterDetail(**data)


@router.get("", response_model=List[schemas.VksClusterOut])
def list_vks_clusters(supervisor_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.VksCluster)
    if supervisor_id is not None:
        q = q.filter(models.VksCluster.supervisor_id == supervisor_id)
    return q.all()


@router.post("", response_model=schemas.VksClusterOut, status_code=201)
def create_vks_cluster(body: schemas.VksClusterCreate, db: Session = Depends(get_db)):
    sup = db.get(models.SupervisorCluster, body.supervisor_id)
    if not sup:
        raise HTTPException(404, "Supervisor not found")

    cluster = models.VksCluster(
        supervisor_id=body.supervisor_id,
        name=body.name,
        namespace=body.namespace,
        k8s_version=body.k8s_version,
        control_plane_nodes=body.control_plane_nodes,
        worker_nodes=body.worker_nodes,
        status=models.VksClusterStatus.UNMANAGED,
    )
    db.add(cluster)
    db.commit()
    db.refresh(cluster)
    return cluster


@router.get("/{cluster_id}", response_model=schemas.VksClusterDetail)
def get_vks_cluster(cluster_id: int, db: Session = Depends(get_db)):
    return _to_detail(_get_cluster_or_404(db, cluster_id))


@router.post("/{cluster_id}/manage", response_model=schemas.VksClusterDetail)
def manage_cluster(cluster_id: int, db: Session = Depends(get_db)):
    """Transition a cluster from unmanaged to managed: deploy the
    VKS-scoped agent pod into the cluster and collect its current
    configuration/deployment inventory. Mirrors TMC's "Attach
    Cluster" flow (generate manifest -> apply -> agent reports in)."""
    cluster = _get_cluster_or_404(db, cluster_id)
    if cluster.status == models.VksClusterStatus.MANAGED:
        raise HTTPException(400, "Cluster is already managed")

    cluster.agent_pod_name = f"agent-vks-{cluster.name}"
    cluster.agent_version = AGENT_VERSION
    cluster.status = models.VksClusterStatus.MANAGED
    cluster.last_sync = simulate_heartbeat()
    cluster.inventory_json = json.dumps(
        build_inventory(cluster.name, cluster.namespace or "default")
    )
    db.commit()
    db.refresh(cluster)
    return _to_detail(cluster)


@router.post("/{cluster_id}/unmanage", response_model=schemas.VksClusterOut)
def unmanage_cluster(cluster_id: int, db: Session = Depends(get_db)):
    """Tear down the VKS-scoped agent pod and stop collecting
    inventory for this cluster."""
    cluster = _get_cluster_or_404(db, cluster_id)
    cluster.status = models.VksClusterStatus.UNMANAGED
    cluster.agent_pod_name = None
    cluster.agent_version = None
    cluster.last_sync = None
    cluster.inventory_json = None
    db.commit()
    db.refresh(cluster)
    return cluster


@router.post("/{cluster_id}/sync", response_model=schemas.VksClusterDetail)
def resync_inventory(cluster_id: int, db: Session = Depends(get_db)):
    """Force a refresh of the collected inventory from the agent pod."""
    cluster = _get_cluster_or_404(db, cluster_id)
    if cluster.status != models.VksClusterStatus.MANAGED:
        raise HTTPException(400, "Cluster must be managed before it can be synced")
    cluster.last_sync = simulate_heartbeat()
    cluster.inventory_json = json.dumps(
        build_inventory(cluster.name, cluster.namespace or "default")
    )
    db.commit()
    db.refresh(cluster)
    return _to_detail(cluster)


@router.post("/{cluster_id}/resize", response_model=schemas.VksClusterOut)
def resize_cluster(cluster_id: int, body: schemas.ResizeRequest, db: Session = Depends(get_db)):
    cluster = _get_cluster_or_404(db, cluster_id)
    if body.control_plane_nodes is not None:
        cluster.control_plane_nodes = body.control_plane_nodes
    if body.worker_nodes is not None:
        cluster.worker_nodes = body.worker_nodes
    db.commit()
    db.refresh(cluster)
    return cluster


@router.post("/{cluster_id}/upgrade", response_model=schemas.VksClusterOut)
def upgrade_cluster(cluster_id: int, body: schemas.UpgradeRequest, db: Session = Depends(get_db)):
    """Simulate a rolling upgrade: in a real deployment this would be
    asynchronous with a progress callback from the agent pod; here it
    completes immediately for simplicity."""
    cluster = _get_cluster_or_404(db, cluster_id)
    cluster.k8s_version = body.target_version
    db.commit()
    db.refresh(cluster)
    return cluster


@router.delete("/{cluster_id}", status_code=204)
def delete_cluster(cluster_id: int, db: Session = Depends(get_db)):
    cluster = _get_cluster_or_404(db, cluster_id)
    db.delete(cluster)
    db.commit()


# ---------------------------------------------------------------------
# Real agent integration surface (see the matching block in
# routers/supervisors.py for the overall bootstrap/session pattern).
# The demo endpoints above (/manage, /sync, ...) fabricate inventory
# locally so the dashboard works without a real VKS cluster. These
# endpoints are what the VKS-scoped agent pod, deployed via
# vks-agent.yaml after clicking "Manage", actually calls.
# ---------------------------------------------------------------------


@router.post("/{cluster_id}/agent/bootstrap", response_model=schemas.BootstrapTokenOut)
def issue_vks_bootstrap_token(cluster_id: int, db: Session = Depends(get_db)):
    """Admin-initiated (this is what the portal's real "Manage"
    action calls): mint a short-lived token to embed in the Secret
    shipped with vks-agent.yaml before applying it to the target
    VKS cluster."""
    cluster = _get_cluster_or_404(db, cluster_id)
    if cluster.status == models.VksClusterStatus.MANAGED:
        raise HTTPException(400, "Cluster is already managed")
    cluster.bootstrap_token = new_token()
    cluster.status = models.VksClusterStatus.PENDING
    db.commit()
    return schemas.BootstrapTokenOut(bootstrap_token=cluster.bootstrap_token)


@router.post("/{cluster_id}/agent/register", response_model=schemas.VksClusterOut)
def vks_agent_register(
    cluster_id: int,
    body: schemas.VksAgentRegisterRequest,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    cluster = _get_cluster_or_404(db, cluster_id)
    token = extract_bearer(authorization)
    if not cluster.bootstrap_token or token != cluster.bootstrap_token:
        raise HTTPException(401, "Invalid or expired bootstrap token")

    cluster.agent_pod_name = body.agent_pod_name
    cluster.agent_version = body.agent_version
    cluster.agent_token = body.agent_token
    cluster.bootstrap_token = None
    db.commit()
    db.refresh(cluster)
    return cluster


@router.post("/{cluster_id}/agent/report", response_model=schemas.VksClusterDetail)
def vks_agent_report(
    cluster_id: int,
    body: schemas.VksAgentReportRequest,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Agent-initiated: push the configuration/deployment inventory
    it collected from the VKS cluster. Flips the cluster to
    'managed' once real data has actually arrived."""
    cluster = _get_cluster_or_404(db, cluster_id)
    token = extract_bearer(authorization)
    if not cluster.agent_token or token != cluster.agent_token:
        raise HTTPException(401, "Invalid session token")

    cluster.inventory_json = json.dumps(body.inventory)
    cluster.status = models.VksClusterStatus.MANAGED
    cluster.last_sync = datetime.utcnow()
    db.commit()
    db.refresh(cluster)
    return _to_detail(cluster)

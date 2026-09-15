"""
Seed the database with a small demo dataset so the portal has
something to show right after `docker run`.
"""
from sqlalchemy.orm import Session

from app import models


def seed_if_empty(db: Session) -> None:
    if db.query(models.SupervisorCluster).count() > 0:
        return

    sup1 = models.SupervisorCluster(
        name="vcf-seoul-dc01",
        vcf_instance="sc-seoul-01",
        agent_status=models.SupervisorAgentStatus.RUNNING,
        agent_version="v1.4.2",
        secret_registered=True,
        secret_name="vcf-agent-portal-session",
        session_status=models.SessionStatus.CONNECTED,
    )
    sup2 = models.SupervisorCluster(
        name="vcf-busan-dc02",
        vcf_instance="sc-busan-01",
        agent_status=models.SupervisorAgentStatus.NOT_DEPLOYED,
        session_status=models.SessionStatus.DISCONNECTED,
    )
    db.add_all([sup1, sup2])
    db.commit()
    db.refresh(sup1)

    clusters = [
        models.VksCluster(
            supervisor_id=sup1.id,
            name="payment-prod-vks",
            namespace="payment-ns",
            k8s_version="v1.29.4",
            control_plane_nodes=3,
            worker_nodes=6,
            cpu_usage_pct=62,
            mem_usage_pct=71,
            status=models.VksClusterStatus.UNMANAGED,
        ),
        models.VksCluster(
            supervisor_id=sup1.id,
            name="analytics-dev-vks",
            namespace="analytics-ns",
            k8s_version="v1.27.9",
            control_plane_nodes=1,
            worker_nodes=3,
            cpu_usage_pct=34,
            mem_usage_pct=48,
            status=models.VksClusterStatus.UNMANAGED,
        ),
        models.VksCluster(
            supervisor_id=sup1.id,
            name="edge-cache-vks",
            namespace="edge-ns",
            k8s_version="v1.29.4",
            control_plane_nodes=3,
            worker_nodes=4,
            cpu_usage_pct=88,
            mem_usage_pct=92,
            status=models.VksClusterStatus.UNMANAGED,
        ),
    ]
    db.add_all(clusters)
    db.commit()

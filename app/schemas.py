"""
Pydantic schemas used at the API boundary.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class SupervisorCreate(BaseModel):
    name: str
    vcf_instance: str


class SupervisorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    vcf_instance: str
    agent_status: str
    agent_version: Optional[str]
    secret_registered: bool
    secret_name: Optional[str]
    session_status: str
    last_heartbeat: Optional[datetime]
    created_at: datetime


class SecretRegisterRequest(BaseModel):
    secret_name: str = "vcf-agent-portal-session"


class VksClusterCreate(BaseModel):
    supervisor_id: int
    name: str
    namespace: str = "default"
    k8s_version: str = "v1.29.4"
    control_plane_nodes: int = 1
    worker_nodes: int = 2


class VksClusterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supervisor_id: int
    name: str
    namespace: Optional[str]
    k8s_version: str
    control_plane_nodes: int
    worker_nodes: int
    cpu_usage_pct: int
    mem_usage_pct: int
    status: str
    agent_pod_name: Optional[str]
    agent_version: Optional[str]
    last_sync: Optional[datetime]
    created_at: datetime


class VksClusterDetail(VksClusterOut):
    inventory: Optional[Dict[str, Any]] = None


class BootstrapTokenOut(BaseModel):
    bootstrap_token: str


class SupervisorAgentRegisterRequest(BaseModel):
    """Sent by the supervisor agent on first contact. secret_name /
    secret_token describe the Kubernetes Secret the agent itself
    created to hold its session credential."""

    secret_name: str
    secret_token: str


class SupervisorStatusReportRequest(BaseModel):
    """Free-form operational status collected by the supervisor
    agent (node counts, capacity, health, workload domains, ...)."""

    data: Dict[str, Any]


class VksAgentRegisterRequest(BaseModel):
    agent_pod_name: str
    agent_version: str
    agent_token: str


class VksAgentReportRequest(BaseModel):
    inventory: Dict[str, Any]


class ResizeRequest(BaseModel):
    control_plane_nodes: Optional[int] = None
    worker_nodes: Optional[int] = None


class UpgradeRequest(BaseModel):
    target_version: str

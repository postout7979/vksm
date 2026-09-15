"""
ORM models.

SupervisorCluster
    Represents one VCF 9.1 Supervisor cluster registered with the
    portal. The portal deploys an "agent pod" inside the Supervisor,
    which creates a Kubernetes Secret used to keep a persistent
    session between the agent and the portal (heartbeat-based).

VksCluster
    Represents one VKS (VMware vSphere Kubernetes Service) workload
    cluster running under a Supervisor. It starts out "unmanaged".
    Calling the /manage endpoint simulates deploying a second,
    VKS-scoped agent pod inside that cluster, which then reports
    back an inventory (namespaces / workloads / add-ons) that the
    portal stores and displays -- similar to how Tanzu Mission
    Control (TMC) attaches and inspects a cluster.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class SupervisorAgentStatus(str, enum.Enum):
    NOT_DEPLOYED = "not_deployed"
    DEPLOYING = "deploying"
    RUNNING = "running"
    CRASH_LOOP = "crash_loop"


class SessionStatus(str, enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"


class VksClusterStatus(str, enum.Enum):
    UNMANAGED = "unmanaged"
    PENDING = "pending"       # agent pod deployment in progress
    MANAGED = "managed"       # agent pod running, inventory synced
    DEGRADED = "degraded"     # agent lost contact / cluster unhealthy


class SupervisorCluster(Base):
    __tablename__ = "supervisor_clusters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    vcf_instance = Column(String, nullable=False)

    agent_status = Column(
        Enum(SupervisorAgentStatus), default=SupervisorAgentStatus.NOT_DEPLOYED
    )
    agent_version = Column(String, nullable=True)

    secret_registered = Column(Boolean, default=False)
    secret_name = Column(String, nullable=True)

    # Short-lived credential embedded in the deployment YAML's Secret so
    # a freshly-deployed agent pod can authenticate its first call.
    # Cleared once /agent/register succeeds (mirrors TMC's time-limited
    # attach credential).
    bootstrap_token = Column(String, nullable=True)
    # Long-lived credential the agent itself generates, stores in a
    # Kubernetes Secret it creates in its own namespace, and reports to
    # the portal at registration time. Used to authenticate every
    # subsequent heartbeat/status call.
    secret_token = Column(String, nullable=True)

    session_status = Column(Enum(SessionStatus), default=SessionStatus.DISCONNECTED)
    last_heartbeat = Column(DateTime, nullable=True)

    # Latest operational status payload reported by the agent (node
    # counts, capacity, health, etc.), stored as JSON text.
    status_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    vks_clusters = relationship(
        "VksCluster", back_populates="supervisor", cascade="all, delete-orphan"
    )


class VksCluster(Base):
    __tablename__ = "vks_clusters"

    id = Column(Integer, primary_key=True, index=True)
    supervisor_id = Column(Integer, ForeignKey("supervisor_clusters.id"))
    name = Column(String, index=True, nullable=False)
    namespace = Column(String, nullable=True)
    k8s_version = Column(String, nullable=False)

    control_plane_nodes = Column(Integer, default=1)
    worker_nodes = Column(Integer, default=1)

    cpu_usage_pct = Column(Integer, default=0)
    mem_usage_pct = Column(Integer, default=0)

    status = Column(Enum(VksClusterStatus), default=VksClusterStatus.UNMANAGED)

    # VKS-scoped agent pod (deployed only after "Manage" is triggered)
    agent_pod_name = Column(String, nullable=True)
    agent_version = Column(String, nullable=True)
    last_sync = Column(DateTime, nullable=True)

    # Same bootstrap/session token pattern as SupervisorCluster above.
    bootstrap_token = Column(String, nullable=True)
    agent_token = Column(String, nullable=True)

    # Collected configuration / deployment inventory, stored as JSON text.
    # In a fuller implementation this would be normalized into separate
    # Namespace / Workload / Addon tables; a JSON blob keeps the
    # prototype simple while still round-tripping through the API.
    inventory_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    supervisor = relationship("SupervisorCluster", back_populates="vks_clusters")

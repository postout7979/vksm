"""
Agent simulation helpers.

There is no real VCF Supervisor or VKS cluster behind this prototype,
so these functions stand in for what a deployed agent pod would
report back to the portal over its persistent session. Swap these out
for real calls to the agent's reporting API once this is wired up to
an actual VCF 9.1 environment.
"""
import random
from datetime import datetime

AGENT_VERSION = "v1.1.0"

_SAMPLE_ADDONS = [
    "cert-manager",
    "contour",
    "metrics-server",
    "external-dns",
    "velero",
    "prometheus",
]

_SAMPLE_NAMESPACES = ["kube-system", "istio-system", "monitoring", "default"]


def build_inventory(cluster_name: str, namespace: str) -> dict:
    """Simulate the configuration/deployment inventory a VKS-scoped
    agent pod would collect and report after being deployed."""
    namespaces = [namespace] + random.sample(
        _SAMPLE_NAMESPACES, k=random.randint(2, 3)
    )
    namespace_details = []
    total_pods = 0
    for ns in namespaces:
        deployments = random.randint(2, 12)
        pods = deployments * random.randint(2, 4)
        total_pods += pods
        namespace_details.append(
            {"name": ns, "deployments": deployments, "pods": pods}
        )

    addons = random.sample(_SAMPLE_ADDONS, k=random.randint(3, len(_SAMPLE_ADDONS)))

    return {
        "namespaces": namespace_details,
        "namespace_count": len(namespace_details),
        "workload_count": sum(n["deployments"] for n in namespace_details),
        "pod_count": total_pods,
        "addons": addons,
        "collected_at": datetime.utcnow().isoformat(),
    }


def simulate_heartbeat() -> datetime:
    return datetime.utcnow()


def simulate_resource_usage() -> tuple[int, int]:
    return random.randint(20, 90), random.randint(20, 90)

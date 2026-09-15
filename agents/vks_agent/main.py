"""
VKS agent.

Deployed inside a specific VKS (VMware vSphere Kubernetes Service)
workload cluster by k8s/vks-agent.yaml, only after that cluster is put
into "Managed" state from the portal (which mints the bootstrap token
this agent consumes on first contact).

Responsibilities:

  1. On startup, exchange the bootstrap token for a session: generate
     a session token and register it with the portal along with this
     pod's own name/version.
  2. Every REPORT_INTERVAL_SECONDS, walk the cluster's namespaces and
     workloads, detect a fixed set of well-known add-ons, and push the
     resulting inventory to the portal. This mirrors what the portal
     dashboard already displays for a "managed" VKS cluster.

Like the supervisor agent, this degrades to a mock inventory if run
outside a real cluster so the register/report loop is still testable
end-to-end against the portal.
"""
import logging
import os
import secrets
import time
from datetime import datetime, timezone

import requests

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("vks-agent")

PORTAL_URL = os.environ["PORTAL_URL"].rstrip("/")
VKS_CLUSTER_ID = os.environ["VKS_CLUSTER_ID"]
BOOTSTRAP_TOKEN = os.environ["BOOTSTRAP_TOKEN"]
POD_NAME = os.environ.get("POD_NAME", "vks-agent")
AGENT_VERSION = os.environ.get("AGENT_VERSION", "v1.0.0")
REPORT_INTERVAL_SECONDS = int(os.environ.get("REPORT_INTERVAL_SECONDS", "60"))
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))

HEALTH_FILE = os.environ.get("HEALTH_FILE", "/tmp/agent-healthy")

# Well-known add-ons we can recognize by a Deployment/DaemonSet name
# match. Extend this as needed for the add-ons actually shipped in
# your VKS clusters.
KNOWN_ADDON_WORKLOADS = {
    "cert-manager": "cert-manager",
    "contour": "contour",
    "metrics-server": "metrics-server",
    "external-dns": "external-dns",
    "velero": "velero",
    "prometheus": "prometheus-server",
}


def _load_k8s_clients():
    try:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        return client.CoreV1Api(), client.AppsV1Api()
    except Exception as exc:  # pragma: no cover - environment dependent
        log.warning("Kubernetes API unavailable, running with mock data: %s", exc)
        return None, None


def collect_inventory(core_v1, apps_v1) -> dict:
    if core_v1 is None or apps_v1 is None:
        return {
            "namespaces": [],
            "namespace_count": 0,
            "workload_count": 0,
            "pod_count": 0,
            "addons": [],
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "source": "mock",
        }

    namespaces = core_v1.list_namespace().items
    all_deployments = apps_v1.list_deployment_for_all_namespaces().items
    all_pods = core_v1.list_pod_for_all_namespaces().items

    namespace_details = []
    for ns in namespaces:
        ns_name = ns.metadata.name
        deployments_in_ns = [d for d in all_deployments if d.metadata.namespace == ns_name]
        pods_in_ns = [p for p in all_pods if p.metadata.namespace == ns_name]
        namespace_details.append(
            {
                "name": ns_name,
                "deployments": len(deployments_in_ns),
                "pods": len(pods_in_ns),
            }
        )

    deployment_names = {d.metadata.name for d in all_deployments}
    detected_addons = [
        addon
        for addon, workload_name in KNOWN_ADDON_WORKLOADS.items()
        if any(workload_name in name for name in deployment_names)
    ]

    return {
        "namespaces": namespace_details,
        "namespace_count": len(namespace_details),
        "workload_count": len(all_deployments),
        "pod_count": len(all_pods),
        "addons": detected_addons,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source": "live",
    }


class PortalClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session_token: str | None = None

    def _headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def register(self, agent_pod_name: str, agent_version: str, agent_token: str) -> dict:
        resp = requests.post(
            f"{self.base_url}/api/vks-clusters/{VKS_CLUSTER_ID}/agent/register",
            headers=self._headers(BOOTSTRAP_TOKEN),
            json={
                "agent_pod_name": agent_pod_name,
                "agent_version": agent_version,
                "agent_token": agent_token,
            },
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        self.session_token = agent_token
        return resp.json()

    def report(self, inventory: dict) -> dict:
        resp = requests.post(
            f"{self.base_url}/api/vks-clusters/{VKS_CLUSTER_ID}/agent/report",
            headers=self._headers(self.session_token),
            json={"inventory": inventory},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()


def main() -> None:
    core_v1, apps_v1 = _load_k8s_clients()
    portal = PortalClient(PORTAL_URL)

    session_token = secrets.token_urlsafe(32)
    log.info("Registering with portal at %s (vks_cluster_id=%s)", PORTAL_URL, VKS_CLUSTER_ID)
    portal.register(POD_NAME, AGENT_VERSION, session_token)
    log.info("Registered. Entering report loop every %ss", REPORT_INTERVAL_SECONDS)

    while True:
        try:
            inventory = collect_inventory(core_v1, apps_v1)
            portal.report(inventory)
            with open(HEALTH_FILE, "w") as f:
                f.write(datetime.now(timezone.utc).isoformat())
            log.info(
                "Reported inventory: namespaces=%s workloads=%s pods=%s addons=%s",
                inventory.get("namespace_count"),
                inventory.get("workload_count"),
                inventory.get("pod_count"),
                inventory.get("addons"),
            )
        except requests.RequestException as exc:
            log.warning("Portal communication failed, will retry: %s", exc)
        except Exception:
            log.exception("Unexpected error in report loop")

        time.sleep(REPORT_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

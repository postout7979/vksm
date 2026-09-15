"""
Supervisor agent.

Deployed inside a VCF 9.1 Supervisor cluster by k8s/supervisor-agent.yaml.
Responsibilities:

  1. On startup, exchange the one-time bootstrap token (mounted from a
     Secret) for a long-lived session: generate a session token,
     create a Kubernetes Secret in its own namespace to hold it (this
     is the "agent pod가 생성한 secret"), and register both with the
     portal.
  2. Every REPORT_INTERVAL_SECONDS, collect basic operational status
     from the Supervisor cluster and push it to the portal, along
     with a heartbeat that keeps the session marked "connected".

Kubernetes API access is optional at import time: if the agent is run
outside a cluster (e.g. for local testing against the portal), it
falls back to an empty/best-effort status payload instead of crashing,
so the register/heartbeat/status loop can still be exercised.
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
log = logging.getLogger("supervisor-agent")

PORTAL_URL = os.environ["PORTAL_URL"].rstrip("/")
SUPERVISOR_ID = os.environ["SUPERVISOR_ID"]
BOOTSTRAP_TOKEN = os.environ["BOOTSTRAP_TOKEN"]
AGENT_NAMESPACE = os.environ.get("AGENT_NAMESPACE", "vcf-agent-system")
SECRET_NAME = os.environ.get("SESSION_SECRET_NAME", "supervisor-agent-session")
REPORT_INTERVAL_SECONDS = int(os.environ.get("REPORT_INTERVAL_SECONDS", "30"))
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))

HEALTH_FILE = os.environ.get("HEALTH_FILE", "/tmp/agent-healthy")


# --------------------------------------------------------------------
# Kubernetes access (best-effort; degrades gracefully outside a cluster)
# --------------------------------------------------------------------
def _load_k8s_clients():
    try:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        return client.CoreV1Api()
    except Exception as exc:  # pragma: no cover - environment dependent
        log.warning("Kubernetes API unavailable, running with mock data: %s", exc)
        return None


def create_session_secret(core_v1, session_token: str) -> None:
    """Create (or update) the Kubernetes Secret the agent uses to
    persist its session token across restarts."""
    if core_v1 is None:
        log.info("Skipping Secret creation (no cluster access)")
        return

    from kubernetes.client import V1ObjectMeta, V1Secret
    from kubernetes.client.rest import ApiException

    body = V1Secret(
        metadata=V1ObjectMeta(name=SECRET_NAME, namespace=AGENT_NAMESPACE),
        string_data={"session-token": session_token},
        type="Opaque",
    )
    try:
        core_v1.create_namespaced_secret(namespace=AGENT_NAMESPACE, body=body)
        log.info("Created session Secret %s/%s", AGENT_NAMESPACE, SECRET_NAME)
    except ApiException as exc:
        if exc.status == 409:
            core_v1.replace_namespaced_secret(
                name=SECRET_NAME, namespace=AGENT_NAMESPACE, body=body
            )
            log.info("Updated existing session Secret %s/%s", AGENT_NAMESPACE, SECRET_NAME)
        else:
            raise


def collect_supervisor_status(core_v1) -> dict:
    """Collect a basic operational snapshot of the Supervisor cluster.

    This intentionally sticks to generic, always-available Kubernetes
    objects (Nodes, Namespaces) so the agent works against any cluster
    for testing. In a real VCF 9.1 deployment, extend this function to
    also read Supervisor-specific custom resources (e.g. WCP /
    vSphere Namespace objects, ResourcePool and StoragePolicy CRs)
    via a CustomObjectsApi client.
    """
    if core_v1 is None:
        return {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "source": "mock",
            "node_count": 0,
            "ready_nodes": 0,
            "namespace_count": 0,
        }

    nodes = core_v1.list_node().items
    ready_nodes = sum(
        1
        for n in nodes
        for cond in (n.status.conditions or [])
        if cond.type == "Ready" and cond.status == "True"
    )
    namespaces = core_v1.list_namespace().items

    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source": "live",
        "node_count": len(nodes),
        "ready_nodes": ready_nodes,
        "namespace_count": len(namespaces),
        "namespaces": [ns.metadata.name for ns in namespaces],
    }


# --------------------------------------------------------------------
# Portal client
# --------------------------------------------------------------------
class PortalClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session_token: str | None = None

    def _headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def register(self, secret_name: str, secret_token: str) -> dict:
        resp = requests.post(
            f"{self.base_url}/api/supervisors/{SUPERVISOR_ID}/agent/register",
            headers=self._headers(BOOTSTRAP_TOKEN),
            json={"secret_name": secret_name, "secret_token": secret_token},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        self.session_token = secret_token
        return resp.json()

    def heartbeat(self) -> dict:
        resp = requests.post(
            f"{self.base_url}/api/supervisors/{SUPERVISOR_ID}/agent/heartbeat",
            headers=self._headers(self.session_token),
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def report_status(self, data: dict) -> None:
        resp = requests.post(
            f"{self.base_url}/api/supervisors/{SUPERVISOR_ID}/agent/status",
            headers=self._headers(self.session_token),
            json={"data": data},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()


def main() -> None:
    core_v1 = _load_k8s_clients()
    portal = PortalClient(PORTAL_URL)

    session_token = secrets.token_urlsafe(32)
    create_session_secret(core_v1, session_token)

    log.info("Registering with portal at %s (supervisor_id=%s)", PORTAL_URL, SUPERVISOR_ID)
    portal.register(SECRET_NAME, session_token)
    log.info("Registered. Entering report loop every %ss", REPORT_INTERVAL_SECONDS)

    while True:
        try:
            portal.heartbeat()
            status = collect_supervisor_status(core_v1)
            portal.report_status(status)
            with open(HEALTH_FILE, "w") as f:
                f.write(datetime.now(timezone.utc).isoformat())
            log.info(
                "Reported status: nodes=%s ready=%s namespaces=%s",
                status.get("node_count"),
                status.get("ready_nodes"),
                status.get("namespace_count"),
            )
        except requests.RequestException as exc:
            log.warning("Portal communication failed, will retry: %s", exc)
        except Exception:
            log.exception("Unexpected error in report loop")

        time.sleep(REPORT_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

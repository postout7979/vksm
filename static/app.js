const $ = (sel) => document.querySelector(sel);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    alert(`요청 실패 (${res.status}): ${body.detail || res.statusText}`);
    throw new Error(body.detail || res.statusText);
  }
  if (res.status === 204) return null;
  return res.json();
}

function fmt(ts) {
  if (!ts) return "-";
  return new Date(ts).toLocaleString("ko-KR");
}

async function loadSupervisors() {
  const list = await api("/api/supervisors");
  const el = $("#supervisors");
  el.innerHTML = "";
  list.forEach((s) => el.appendChild(renderSupervisorCard(s)));
  populateSupervisorSelect(list);
}

function populateSupervisorSelect(list) {
  const select = document.querySelector('#form-add-vks select[name="supervisor_id"]');
  if (!select) return;
  const current = select.value;
  select.innerHTML = list
    .map((s) => `<option value="${s.id}">${s.name} (${s.vcf_instance})</option>`)
    .join("");
  if (current) select.value = current;
}

function renderSupervisorCard(s) {
  const div = document.createElement("div");
  div.className = "card";
  div.innerHTML = `
    <div class="card-top">
      <div>
        <p class="card-title">${s.name}</p>
        <p class="card-sub">${s.vcf_instance}</p>
      </div>
      <span class="badge ${s.session_status}">${s.session_status}</span>
    </div>
    <div class="card-body">
      <div><span class="k">Agent Pod</span>${s.agent_status}</div>
      <div><span class="k">Secret</span>${s.secret_registered ? s.secret_name : "미등록"}</div>
      <div><span class="k">마지막 heartbeat</span>${fmt(s.last_heartbeat)}</div>
      <div><span class="k">Agent 버전</span>${s.agent_version || "-"}</div>
    </div>
    <div class="card-actions">
      <button data-act="deploy" ${s.agent_status === "running" ? "disabled" : ""}>Agent 배포</button>
      <button data-act="secret" ${s.agent_status !== "running" || s.secret_registered ? "disabled" : ""}>Secret 등록</button>
      <button data-act="heartbeat" ${!s.secret_registered ? "disabled" : ""}>Heartbeat 전송</button>
      <button data-act="delete">삭제</button>
    </div>
  `;
  div.querySelector('[data-act="deploy"]').onclick = async () => {
    await api(`/api/supervisors/${s.id}/deploy-agent`, { method: "POST" });
    loadSupervisors();
  };
  div.querySelector('[data-act="secret"]').onclick = async () => {
    await api(`/api/supervisors/${s.id}/register-secret`, {
      method: "POST",
      body: JSON.stringify({ secret_name: `vcf-agent-portal-session-${s.id}` }),
    });
    loadSupervisors();
  };
  div.querySelector('[data-act="heartbeat"]').onclick = async () => {
    await api(`/api/supervisors/${s.id}/heartbeat`, { method: "POST" });
    loadSupervisors();
  };
  div.querySelector('[data-act="delete"]').onclick = async () => {
    if (!confirm(`${s.name} 을(를) 삭제할까요?`)) return;
    await api(`/api/supervisors/${s.id}`, { method: "DELETE" });
    loadSupervisors();
    loadVksClusters();
  };
  return div;
}

async function loadVksClusters() {
  const list = await api("/api/vks-clusters");
  const el = $("#vks-clusters");
  el.innerHTML = "";
  list.forEach((c) => el.appendChild(renderVksCard(c)));
}

function renderVksCard(c) {
  const div = document.createElement("div");
  div.className = "card";
  div.innerHTML = `
    <div class="card-top">
      <div>
        <p class="card-title">${c.name}</p>
        <p class="card-sub">${c.k8s_version} · Ctrl ${c.control_plane_nodes} / Wkr ${c.worker_nodes}</p>
      </div>
      <span class="badge ${c.status}">${c.status}</span>
    </div>
    <div class="card-body">
      <div><span class="k">CPU</span>${c.cpu_usage_pct}%</div>
      <div><span class="k">Memory</span>${c.mem_usage_pct}%</div>
      <div><span class="k">Agent Pod</span>${c.agent_pod_name || "미배포"}</div>
      <div><span class="k">마지막 동기화</span>${fmt(c.last_sync)}</div>
    </div>
    <div class="card-actions">
      <button data-act="manage" ${c.status === "managed" ? "disabled" : ""}>Manage</button>
      <button data-act="unmanage" ${c.status !== "managed" ? "disabled" : ""}>Unmanage</button>
      <button data-act="sync" ${c.status !== "managed" ? "disabled" : ""}>재동기화</button>
      <button data-act="resize">리사이즈 +1 Wkr</button>
      <button data-act="upgrade">업그레이드</button>
      <button data-act="delete">삭제</button>
    </div>
    <div data-slot="inventory"></div>
  `;
  div.querySelector('[data-act="manage"]').onclick = async () => {
    const detail = await api(`/api/vks-clusters/${c.id}/manage`, { method: "POST" });
    loadVksClusters();
    showInventory(div, detail.inventory);
  };
  div.querySelector('[data-act="unmanage"]').onclick = async () => {
    await api(`/api/vks-clusters/${c.id}/unmanage`, { method: "POST" });
    loadVksClusters();
  };
  div.querySelector('[data-act="sync"]').onclick = async () => {
    const detail = await api(`/api/vks-clusters/${c.id}/sync`, { method: "POST" });
    showInventory(div, detail.inventory);
  };
  div.querySelector('[data-act="resize"]').onclick = async () => {
    await api(`/api/vks-clusters/${c.id}/resize`, {
      method: "POST",
      body: JSON.stringify({ worker_nodes: c.worker_nodes + 1 }),
    });
    loadVksClusters();
  };
  div.querySelector('[data-act="upgrade"]').onclick = async () => {
    const target = prompt("업그레이드할 버전을 입력하세요", "v1.30.1");
    if (!target) return;
    await api(`/api/vks-clusters/${c.id}/upgrade`, {
      method: "POST",
      body: JSON.stringify({ target_version: target }),
    });
    loadVksClusters();
  };
  div.querySelector('[data-act="delete"]').onclick = async () => {
    if (!confirm(`${c.name} 을(를) 삭제할까요?`)) return;
    await api(`/api/vks-clusters/${c.id}`, { method: "DELETE" });
    loadVksClusters();
  };
  return div;
}

function showInventory(cardEl, inventory) {
  const slot = cardEl.querySelector('[data-slot="inventory"]');
  if (!inventory) {
    slot.innerHTML = "";
    return;
  }
  slot.innerHTML = `<pre class="inventory">${JSON.stringify(inventory, null, 2)}</pre>`;
}

loadSupervisors();
loadVksClusters();
setInterval(() => {
  loadSupervisors();
  loadVksClusters();
}, 15000);

// --- Add-Supervisor form ---
const supForm = $("#form-add-supervisor");
$("#btn-show-add-supervisor").onclick = () => supForm.classList.toggle("hidden");
$("#btn-cancel-add-supervisor").onclick = () => {
  supForm.reset();
  supForm.classList.add("hidden");
};
supForm.onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(supForm);
  const sup = await api("/api/supervisors", {
    method: "POST",
    body: JSON.stringify({
      name: fd.get("name"),
      vcf_instance: fd.get("vcf_instance"),
    }),
  });
  supForm.reset();
  supForm.classList.add("hidden");
  loadSupervisors();

  // Mirror TMC-SM's registration flow: right after a management
  // cluster/Supervisor is registered, issue its bootstrap credential
  // and show the ready-to-apply agent manifest.
  const { bootstrap_token } = await api(`/api/supervisors/${sup.id}/agent/bootstrap`, {
    method: "POST",
  });
  showSupervisorYaml(sup, bootstrap_token);
};

function buildSupervisorYaml(sup, bootstrapToken) {
  const portalUrl = window.location.origin;
  return `apiVersion: v1
kind: Namespace
metadata:
  name: vcf-agent-system
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: supervisor-agent
  namespace: vcf-agent-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: supervisor-agent-reader
rules:
  - apiGroups: [""]
    resources: ["nodes", "namespaces"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: supervisor-agent-reader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: supervisor-agent-reader
subjects:
  - kind: ServiceAccount
    name: supervisor-agent
    namespace: vcf-agent-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: supervisor-agent-secret-manager
  namespace: vcf-agent-system
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "create", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: supervisor-agent-secret-manager
  namespace: vcf-agent-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: supervisor-agent-secret-manager
subjects:
  - kind: ServiceAccount
    name: supervisor-agent
    namespace: vcf-agent-system
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: supervisor-agent-config
  namespace: vcf-agent-system
data:
  PORTAL_URL: "${portalUrl}"
  SUPERVISOR_ID: "${sup.id}"
  AGENT_NAMESPACE: "vcf-agent-system"
  SESSION_SECRET_NAME: "supervisor-agent-session"
  REPORT_INTERVAL_SECONDS: "30"
---
# One-time credential -- becomes invalid automatically once this agent
# successfully calls /agent/register on the portal.
apiVersion: v1
kind: Secret
metadata:
  name: supervisor-agent-bootstrap
  namespace: vcf-agent-system
type: Opaque
stringData:
  BOOTSTRAP_TOKEN: "${bootstrapToken}"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: supervisor-agent
  namespace: vcf-agent-system
  labels:
    app: supervisor-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: supervisor-agent
  template:
    metadata:
      labels:
        app: supervisor-agent
    spec:
      serviceAccountName: supervisor-agent
      containers:
        - name: agent
          image: <REGISTRY>/supervisor-agent:latest   # TODO: 빌드한 이미지로 교체
          envFrom:
            - configMapRef:
                name: supervisor-agent-config
            - secretRef:
                name: supervisor-agent-bootstrap
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 250m
              memory: 128Mi
          livenessProbe:
            exec:
              command:
                - sh
                - -c
                - >-
                  test -f /tmp/agent-healthy &&
                  [ $(( $(date +%s) - $(date -r /tmp/agent-healthy +%s) )) -lt 90 ]
            initialDelaySeconds: 15
            periodSeconds: 30
`;
}

function showSupervisorYaml(sup, bootstrapToken) {
  const yaml = buildSupervisorYaml(sup, bootstrapToken);
  const panel = $("#supervisor-yaml-panel");
  const content = $("#supervisor-yaml-content");
  content.textContent = yaml;
  panel.dataset.yaml = yaml;
  panel.dataset.applyCmd = `kubectl config use-context <${sup.name}-supervisor-context>\nkubectl apply -f supervisor-agent.yaml`;
  panel.classList.remove("hidden");
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

$("#btn-copy-supervisor-yaml").onclick = () => {
  navigator.clipboard.writeText($("#supervisor-yaml-panel").dataset.yaml || "");
};
$("#btn-copy-supervisor-apply").onclick = () => {
  navigator.clipboard.writeText($("#supervisor-yaml-panel").dataset.applyCmd || "");
};
$("#btn-close-supervisor-yaml").onclick = () => {
  $("#supervisor-yaml-panel").classList.add("hidden");
};

// --- Add-VKS-cluster form ---
const vksForm = $("#form-add-vks");
$("#btn-show-add-vks").onclick = () => vksForm.classList.toggle("hidden");
$("#btn-cancel-add-vks").onclick = () => {
  vksForm.reset();
  vksForm.classList.add("hidden");
};
vksForm.onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(vksForm);
  await api("/api/vks-clusters", {
    method: "POST",
    body: JSON.stringify({
      supervisor_id: Number(fd.get("supervisor_id")),
      name: fd.get("name"),
      namespace: fd.get("namespace") || "default",
      k8s_version: fd.get("k8s_version") || "v1.29.4",
      control_plane_nodes: Number(fd.get("control_plane_nodes")) || 1,
      worker_nodes: Number(fd.get("worker_nodes")) || 1,
    }),
  });
  vksForm.reset();
  vksForm.classList.add("hidden");
  loadVksClusters();
};

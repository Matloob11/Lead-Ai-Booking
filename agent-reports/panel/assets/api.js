function API_BASE() {
  const saved = localStorage.getItem("ar_api_base");
  if (saved) return saved.replace(/\/$/, "");
  const path = location.pathname || "";
  if (path.includes("/agent-reports")) {
    return path.replace(/\/index\.html$/, "").replace(/\/$/, "") || "/agent-reports";
  }
  return "http://127.0.0.1:8090";
}

async function getJson(path, options) {
  const res = await fetch(`${API_BASE()}${path}`, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

export async function fetchAgents() {
  return getJson("/api/agents");
}

export async function fetchAgentDay(agentId, day) {
  const q = day ? `?day=${encodeURIComponent(day)}` : "";
  return getJson(`/api/agents/${agentId}/day${q}`);
}

export async function fetchReports() {
  return getJson("/api/reports");
}

export async function fetchReportItem(id) {
  return getJson(`/api/reports/items/${id}`);
}

export async function generateReports(body) {
  return getJson("/api/reports/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

export { API_BASE };

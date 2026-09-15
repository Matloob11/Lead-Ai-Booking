import { API_BASE, fetchAgentDay, fetchAgents, fetchReportItem, fetchReports, generateReports } from "./api.js";

const nav = document.querySelectorAll(".ar-nav__btn");
const main = document.querySelector(".ar-main");

function el(tag, props = {}, kids = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "className") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") {
      node.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (v != null) node.setAttribute(k, v);
  }
  for (const child of kids) {
    if (child == null) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function apiBase() {
  return API_BASE();
}

async function showAgents() {
  main.replaceChildren(el("p", { className: "ar-placeholder", text: "Loading Sales / TS agents…" }));
  try {
    const data = await fetchAgents();
    const list = el("div", { className: "ar-list" });
    list.append(
      el("div", { className: "ar-toolbar" }, [
        el("h2", { className: "ar-h2", text: `Agents (${data.count})` }),
        el(
          "button",
          {
            type: "button",
            className: "ar-btn",
            text: "Generate all today (no notify)",
            onclick: async () => {
              if (!window.confirm(`Generate PDFs for ${data.count} Sales/TS agents for today?`)) return;
              main.replaceChildren(
                el("p", {
                  className: "ar-placeholder",
                  text: "Generating all agents — this can take several minutes…",
                })
              );
              try {
                const res = await generateReports({ notify: false, upload: false });
                await showHistory();
                window.alert(`Run #${res.run_id} finished · ${res.agent_count} agents`);
              } catch (err) {
                window.alert(err.message || String(err));
                showAgents();
              }
            },
          }
        ),
      ]),
      el("p", {
        className: "ar-placeholder",
        text: "Click an agent for live snapshot, or Generate PDF for that agent.",
      })
    );
    for (const a of data.agents || []) {
      const row = el("div", { className: "ar-agent-row" }, [
        el(
          "button",
          {
            type: "button",
            className: "ar-agent",
            onclick: () => showDay(a.id, a.name),
          },
          [
            el("strong", { text: a.name }),
            el("span", { text: (a.department_names || []).join(", ") || "—" }),
          ]
        ),
        el("button", {
          type: "button",
          className: "ar-btn ar-btn--sm",
          text: "PDF",
          onclick: async () => {
            try {
              const res = await generateReports({
                agent_ids: [a.id],
                notify: false,
                upload: false,
              });
              if (res.report_id) {
                window.open(`${apiBase()}/api/reports/items/${res.report_id}/pdf`, "_blank");
              }
              window.alert(res.status === "done" ? "PDF ready" : `Status: ${res.status}\n${res.error || ""}`);
            } catch (err) {
              window.alert(err.message || String(err));
            }
          },
        }),
      ]);
      list.append(row);
    }
    main.replaceChildren(list);
  } catch (err) {
    main.replaceChildren(
      el("p", { className: "ar-placeholder", text: `Could not load agents: ${err.message || err}` })
    );
  }
}

async function showDay(agentId, name) {
  main.replaceChildren(el("p", { className: "ar-placeholder", text: `Loading day for ${name}…` }));
  try {
    const snap = await fetchAgentDay(agentId);
    const box = el("div", { className: "ar-day" }, [
      el("button", {
        type: "button",
        className: "ar-back",
        text: "← Agents",
        onclick: () => showAgents(),
      }),
      el("h2", { className: "ar-h2", text: `${snap.agent_name} · ${snap.day}` }),
      el("div", { className: "ar-grid" }, [
        stat("Check-in", snap.timeman?.checked_in ? `Yes (${snap.timeman.status || "—"})` : "No / unknown"),
        stat("Open leads", String(snap.leads?.total_open ?? 0)),
        stat(
          "New leads today",
          String((snap.leads?.new_classic_today || 0) + (snap.leads?.new_owner_data_today || 0))
        ),
        stat("Calls", String(snap.calls?.count ?? 0)),
        stat("Talk min", String(snap.calls?.talk_minutes ?? 0)),
        stat("Tasks open", String(snap.tasks?.open_count ?? 0)),
        stat("Tasks done today", String(snap.tasks?.completed_today ?? 0)),
      ]),
      el("button", {
        type: "button",
        className: "ar-btn",
        text: "Generate PDF + AI summary",
        onclick: async () => {
          try {
            const res = await generateReports({
              agent_ids: [agentId],
              notify: false,
              upload: false,
            });
            if (res.report_id) {
              const item = await fetchReportItem(res.report_id);
              const wrap = el("div", { className: "ar-summary" }, [
                el("strong", { text: "AI summary" }),
                el("p", { text: item.ai_summary || "—" }),
                el("a", {
                  href: `${apiBase()}/api/reports/items/${res.report_id}/pdf`,
                  target: "_blank",
                  text: "Open PDF",
                }),
              ]);
              box.append(wrap);
            }
          } catch (err) {
            window.alert(err.message || String(err));
          }
        },
      }),
    ]);
    if (snap.errors?.length) {
      box.append(
        el("div", { className: "ar-errors" }, [
          el("strong", { text: "Partial errors" }),
          el(
            "ul",
            {},
            snap.errors.map((e) => el("li", { text: e }))
          ),
        ])
      );
    }
    main.replaceChildren(box);
  } catch (err) {
    main.replaceChildren(
      el("p", { className: "ar-placeholder", text: `Could not load day: ${err.message || err}` }),
      el("button", { type: "button", className: "ar-back", text: "← Agents", onclick: () => showAgents() })
    );
  }
}

function stat(label, value) {
  return el("div", { className: "ar-stat" }, [
    el("span", { className: "ar-stat__l", text: label }),
    el("span", { className: "ar-stat__v", text: value }),
  ]);
}

async function showHistory() {
  main.replaceChildren(el("p", { className: "ar-placeholder", text: "Loading history…" }));
  try {
    const data = await fetchReports();
    const wrap = el("div", { className: "ar-list" }, [
      el("h2", { className: "ar-h2", text: `History (${data.count})` }),
    ]);
    if (!data.runs?.length) {
      wrap.append(el("p", { className: "ar-placeholder", text: "No report runs yet. Generate from Agents." }));
      main.replaceChildren(wrap);
      return;
    }
    for (const run of data.runs) {
      const block = el("div", { className: "ar-run" }, [
        el("div", { className: "ar-run__head" }, [
          el("strong", { text: `${run.day} · run #${run.id}` }),
          el("span", { text: `${run.status} · ${run.trigger} · ${run.agent_count} agents` }),
        ]),
      ]);
      for (const r of run.reports || []) {
        block.append(
          el("div", { className: "ar-run__row" }, [
            el("span", { text: `${r.agent_name} · ${r.status}` }),
            r.has_pdf
              ? el("a", {
                  href: `${apiBase()}/api/reports/items/${r.id}/pdf`,
                  target: "_blank",
                  text: "PDF",
                })
              : el("span", { text: r.error ? "failed" : "—" }),
          ])
        );
      }
      wrap.append(block);
    }
    main.replaceChildren(wrap);
  } catch (err) {
    main.replaceChildren(
      el("p", { className: "ar-placeholder", text: `Could not load history: ${err.message || err}` })
    );
  }
}

nav.forEach((btn) => {
  btn.addEventListener("click", () => {
    nav.forEach((b) => b.classList.toggle("is-active", b === btn));
    if (btn.dataset.view === "history") showHistory();
    else showAgents();
  });
});

showAgents();

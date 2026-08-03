/**
 * Reports & Analytics Dashboard Modal
 */

import { reports } from "../api/api.js";
import { clear, el, modal } from "../core/dom.js";
import { icon } from "../core/icons.js";

// Multi-level cache by days -> tab -> data
const cache = {
  7: {},
  30: {},
  90: {},
};

function formatDuration(sec) {
  if (sec === null || sec === undefined || sec === 0) return null;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  if (m >= 60) {
    const h = Math.floor(m / 60);
    const remM = m % 60;
    return `${h}h ${remM}m`;
  }
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function openReportsModal() {
  let activeDays = 7;
  let activeTab = "overview";

  const tabContainer = el("div.rep-tabs");
  const rangeContainer = el("div.rep-range");
  const contentArea = el("div.rep-content");

  const header = el("div.rep-header", {}, [tabContainer, rangeContainer]);
  const modalBody = el("div.rep-modal", {}, [header, contentArea]);

  const dialog = modal("Analytics & Reports", modalBody, { wide: true });

  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "agents", label: "Agents" },
    { id: "numbers", label: "Numbers" },
    { id: "problems", label: "Problems" },
    { id: "templates", label: "Templates" },
  ];

  const ranges = [7, 30, 90];

  function renderHeaderControls() {
    clear(tabContainer);
    clear(rangeContainer);

    for (const t of tabs) {
      const btn = el(
        "button.rep-tab",
        {
          class: activeTab === t.id ? "active" : "",
          onclick: () => {
            activeTab = t.id;
            renderHeaderControls();
            loadActiveTab();
          },
        },
        [t.label]
      );
      tabContainer.append(btn);
    }

    for (const r of ranges) {
      const btn = el(
        "button.rep-range-btn",
        {
          class: activeDays === r ? "active" : "",
          onclick: () => {
            if (activeDays !== r) {
              activeDays = r;
              renderHeaderControls();
              loadActiveTab();
            }
          },
        },
        [`${r} Days`]
      );
      rangeContainer.append(btn);
    }
  }

  async function loadActiveTab() {
    clear(contentArea).append(el("div.na-note", {}, ["Loading report data…"]));

    if (cache[activeDays] && cache[activeDays][activeTab]) {
      renderTabData(cache[activeDays][activeTab]);
      return;
    }

    try {
      let data = null;
      if (activeTab === "overview") data = await reports.summary(activeDays);
      else if (activeTab === "agents") data = await reports.agents(activeDays);
      else if (activeTab === "numbers") data = await reports.numbers(activeDays);
      else if (activeTab === "problems") data = await reports.failures(activeDays);
      else if (activeTab === "templates") data = await reports.templates(activeDays);

      if (!cache[activeDays]) cache[activeDays] = {};
      cache[activeDays][activeTab] = data;

      renderTabData(data);
    } catch (err) {
      clear(contentArea).append(
        el("div.alert", {}, [`Could not load ${activeTab} report: ${err.message || "Network error"}`])
      );
    }
  }

  function renderTabData(data) {
    clear(contentArea);
    if (activeTab === "overview") renderOverview(data);
    else if (activeTab === "agents") renderAgents(data);
    else if (activeTab === "numbers") renderNumbers(data);
    else if (activeTab === "problems") renderProblems(data);
    else if (activeTab === "templates") renderTemplates(data);
  }

  /* ------------------------------------------------------------- OVERVIEW */
  function renderOverview(data) {
    const fr = data.first_response || {};
    const medianStr = formatDuration(fr.median_seconds) || "not enough replies yet";
    const p90Str = formatDuration(fr.p90_seconds);
    const slowestStr = formatDuration(fr.slowest_seconds);

    const cards = el("div.rep-grid", {}, [
      el("div.rep-card", {}, [
        el("div.rep-card__val", {}, [String(data.inbound ?? 0)]),
        el("div.rep-card__lbl", {}, ["Messages Received"]),
      ]),
      el("div.rep-card", {}, [
        el("div.rep-card__val", {}, [String(data.outbound ?? 0)]),
        el("div.rep-card__lbl", {}, ["Messages Sent"]),
      ]),
      el("div.rep-card", {}, [
        el("div.rep-card__val", {}, [String(data.customers ?? 0)]),
        el("div.rep-card__lbl", {}, ["Customers"]),
      ]),
      el("div.rep-card", {}, [
        el("div.rep-card__val", {}, [String(data.chats_active ?? 0)]),
        el("div.rep-card__lbl", {}, ["Active Chats"]),
      ]),
      el("div.rep-card", {}, [
        el("div.rep-card__val", {}, [String(data.windows_open_now ?? 0)]),
        el("div.rep-card__lbl", {}, ["Open Windows"]),
        el("div.rep-card__sub", {}, ["can reply free"]),
      ]),
      el("div.rep-card", { class: (data.unanswered ?? 0) > 0 ? "rep-card--warn" : "" }, [
        el("div.rep-card__val", {}, [String(data.unanswered ?? 0)]),
        el("div.rep-card__lbl", {}, ["Waiting for Reply"]),
      ]),
      el("div.rep-card.rep-card--lg", {}, [
        el("div.rep-card__val", {}, [medianStr]),
        el("div.rep-card__lbl", {}, ["First Response Time"]),
        fr.count > 0 && (p90Str || slowestStr)
          ? el("div.rep-card__sub", {}, [
              `90% under ${p90Str || "—"} · slowest ${slowestStr || "—"}`,
            ])
          : el("div.rep-card__sub", {}, ["not enough replies yet"]),
      ]),
    ]);

    const failureNote = data.failed > 0
      ? el("div", { style: "margin-bottom: 14px; font-size: 13px; color: rgba(255,255,255,0.7);" }, [
          `${data.failed} sends failed — `,
          el("a", {
            href: "#",
            style: "color: #25d366; text-decoration: underline;",
            onclick: (e) => {
              e.preventDefault();
              activeTab = "problems";
              renderHeaderControls();
              loadActiveTab();
            },
          }, ["see Problems"]),
        ])
      : null;

    // Daily Chart (SVG Grouped Bars)
    const daily = data.daily || [];
    const chart = renderDailyChart(daily, activeDays);

    contentArea.append(cards, failureNote, chart);
  }

  function renderDailyChart(daily, days) {
    if (!daily.length) return el("div.tplc-empty", {}, ["Nothing happened in this period."]);

    const maxVal = Math.max(1, ...daily.map((d) => Math.max(d.in || 0, d.out || 0)));
    const svgWidth = 800;
    const svgHeight = 160;
    const paddingB = 24;
    const paddingT = 10;
    const chartHeight = svgHeight - paddingB - paddingT;
    const pointWidth = svgWidth / daily.length;
    const barW = Math.max(2, Math.min(10, pointWidth / 3));

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${svgWidth} ${svgHeight}`);
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "180");
    svg.style.overflow = "visible";

    daily.forEach((d, i) => {
      const cx = i * pointWidth + pointWidth / 2;
      const inH = ((d.in || 0) / maxVal) * chartHeight;
      const outH = ((d.out || 0) / maxVal) * chartHeight;

      // Inbound bar (Blue)
      const rectIn = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rectIn.setAttribute("x", cx - barW - 1);
      rectIn.setAttribute("y", svgHeight - paddingB - inH);
      rectIn.setAttribute("width", barW);
      rectIn.setAttribute("height", inH);
      rectIn.setAttribute("fill", "#3b82f6");
      rectIn.setAttribute("rx", "2");

      const titleIn = document.createElementNS("http://www.w3.org/2000/svg", "title");
      titleIn.textContent = `${d.date} · ${d.in || 0} in · ${d.out || 0} out`;
      rectIn.appendChild(titleIn);

      // Outbound bar (Green)
      const rectOut = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rectOut.setAttribute("x", cx + 1);
      rectOut.setAttribute("y", svgHeight - paddingB - outH);
      rectOut.setAttribute("width", barW);
      rectOut.setAttribute("height", outH);
      rectOut.setAttribute("fill", "#25d366");
      rectOut.setAttribute("rx", "2");

      const titleOut = document.createElementNS("http://www.w3.org/2000/svg", "title");
      titleOut.textContent = `${d.date} · ${d.in || 0} in · ${d.out || 0} out`;
      rectOut.appendChild(titleOut);

      svg.appendChild(rectIn);
      svg.appendChild(rectOut);

      // Date labels
      const showLabel = days <= 7 || i % 7 === 0 || i === daily.length - 1;
      if (showLabel) {
        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", cx);
        text.setAttribute("y", svgHeight - 6);
        text.setAttribute("fill", "rgba(255,255,255,0.5)");
        text.setAttribute("font-size", "10");
        text.setAttribute("text-anchor", "middle");
        const parts = d.date.split("-");
        text.textContent = parts.length === 3 ? `${parts[2]}/${parts[1]}` : d.date;
        svg.appendChild(text);
      }
    });

    return el("div.rep-chart-box", {}, [
      el("div.rep-chart-title", {}, [
        "Daily Message Activity",
        el("div.rep-chart-legend", {}, [
          el("div.rep-legend-item", {}, [el("span.rep-dot.rep-dot--in"), "Inbound"]),
          el("div.rep-legend-item", {}, [el("span.rep-dot.rep-dot--out"), "Outbound"]),
        ]),
      ]),
      svg,
    ]);
  }

  /* -------------------------------------------------------------- AGENTS */
  function renderAgents(list) {
    if (!list || !list.length) {
      contentArea.append(el("div.tplc-empty", {}, ["Nothing happened in this period."]));
      return;
    }

    let sortCol = "sent";
    let sortAsc = false;

    function renderTable() {
      clear(contentArea);
      const sorted = [...list].sort((a, b) => {
        let va = a[sortCol];
        let vb = b[sortCol];
        if (sortCol === "median_reply") {
          va = a.first_response?.median_seconds ?? 999999;
          vb = b.first_response?.median_seconds ?? 999999;
        }
        if (va < vb) return sortAsc ? -1 : 1;
        if (va > vb) return sortAsc ? 1 : -1;
        return 0;
      });

      const tbody = el("tbody");
      for (const ag of sorted) {
        const failedHigh = ag.sent > 0 && ag.failed / ag.sent > 0.1;
        const medianStr = formatDuration(ag.first_response?.median_seconds) || "—";

        tbody.append(
          el("tr", {}, [
            el("td", { style: "font-weight: 600;" }, [ag.display_name]),
            el("td", {}, [String(ag.sent)]),
            el("td", {}, [String(ag.delivered)]),
            el("td", {}, [String(ag.read)]),
            el("td", { style: failedHigh ? "color: #ef4444; font-weight: 700;" : "" }, [String(ag.failed)]),
            el("td", {}, [String(ag.templates)]),
            el("td", {}, [String(ag.chats)]),
            el("td", {}, [medianStr]),
          ])
        );
      }

      const headers = [
        { id: "display_name", label: "Agent" },
        { id: "sent", label: "Sent" },
        { id: "delivered", label: "Delivered" },
        { id: "read", label: "Read" },
        { id: "failed", label: "Failed" },
        { id: "templates", label: "Templates" },
        { id: "chats", label: "Chats" },
        { id: "median_reply", label: "Median reply" },
      ];

      const thead = el("thead", {}, [
        el(
          "tr",
          {},
          headers.map((h) =>
            el(
              "th",
              {
                onclick: () => {
                  if (sortCol === h.id) sortAsc = !sortAsc;
                  else {
                    sortCol = h.id;
                    sortAsc = false;
                  }
                  renderTable();
                },
              },
              [`${h.label} ${sortCol === h.id ? (sortAsc ? "↑" : "↓") : ""}`]
            )
          )
        ),
      ]);

      const tableWrap = el("div.rep-table-wrap", {}, [el("table.rep-table", {}, [thead, tbody])]);
      const note = el(
        "div",
        { style: "margin-top: 10px; font-size: 12px; opacity: 0.6;" },
        ["Only agents who sent something in this period appear here."]
      );

      contentArea.append(tableWrap, note);
    }

    renderTable();
  }

  /* ------------------------------------------------------------- NUMBERS */
  function renderNumbers(list) {
    if (!list || !list.length) {
      contentArea.append(el("div.tplc-empty", {}, ["Nothing happened in this period."]));
      return;
    }

    let filterAttention = false;

    function renderList() {
      clear(contentArea);
      const filtered = filterAttention
        ? list.filter((n) => !n.agents?.length || n.approved_templates === 0)
        : list;

      const checkbox = el("input", {
        type: "checkbox",
        checked: filterAttention,
        onchange: () => {
          filterAttention = checkbox.checked;
          renderList();
        },
      });

      const topFilter = el(
        "label",
        { style: "display: flex; align-items: center; gap: 8px; margin-bottom: 12px; font-size: 13px; cursor: pointer;" },
        [checkbox, "Only numbers needing attention"]
      );

      if (!filtered.length) {
        contentArea.append(topFilter, el("div.tplc-empty", {}, ["No numbers match filter."]));
        return;
      }

      const tbody = el("tbody");
      for (const num of filtered) {
        const titleCell = el("td", {}, [
          el("div", { style: "font-weight: 600;" }, [num.title]),
          num.phone_number && num.phone_number !== num.title
            ? el("div", { style: "font-size: 11px; opacity: 0.7;" }, [num.phone_number])
            : null,
        ]);

        const noAgents = !num.agents || !num.agents.length;
        const noTemplates = num.approved_templates === 0;

        const agentsCell = el("td", {}, [
          noAgents
            ? el("span.rep-chip.rep-chip--amber", {}, ["Nobody assigned"])
            : num.agents.map((a) => a.display_name || a).join(", "),
        ]);

        const templatesCell = el("td", {}, [
          noTemplates
            ? el(
                "span.rep-chip.rep-chip--amber",
                {
                  title:
                    "This number can only answer customers who write first — with no approved template a closed window cannot be reopened.",
                },
                ["No templates"]
              )
            : String(num.approved_templates),
        ]);

        tbody.append(
          el("tr", {}, [
            titleCell,
            el("td", {}, [String(num.inbound)]),
            el("td", {}, [String(num.outbound)]),
            el("td", {}, [String(num.chats)]),
            el("td", {}, [String(num.windows_open)]),
            templatesCell,
            agentsCell,
            el("td", { style: num.failed > 0 ? "color: #ef4444; font-weight: 600;" : "" }, [String(num.failed)]),
          ])
        );
      }

      const thead = el("thead", {}, [
        el("tr", {}, [
          el("th", {}, ["Number"]),
          el("th", {}, ["In"]),
          el("th", {}, ["Out"]),
          el("th", {}, ["Chats"]),
          el("th", {}, ["Open windows"]),
          el("th", {}, ["Templates"]),
          el("th", {}, ["Agents"]),
          el("th", {}, ["Failed"]),
        ]),
      ]);

      const tableWrap = el("div.rep-table-wrap", {}, [el("table.rep-table", {}, [thead, tbody])]);
      contentArea.append(topFilter, tableWrap);
    }

    renderList();
  }

  /* ------------------------------------------------------------ PROBLEMS */
  function renderProblems(payload) {
    const total = payload.total ?? 0;
    const reasons = payload.reasons || [];

    if (!reasons.length) {
      contentArea.append(el("div.tplc-empty", {}, ["No failures recorded in this period."]));
      return;
    }

    const attentionReasons = reasons.filter((r) => r.actionable);
    const rulesReasons = reasons.filter((r) => !r.actionable);

    const attentionCount = attentionReasons.reduce((s, r) => s + (r.count || 0), 0);
    const rulesCount = rulesReasons.reduce((s, r) => s + (r.count || 0), 0);

    const summaryLine = el("div", { style: "margin-bottom: 16px; font-size: 14px; font-weight: 600;" }, [
      `${total} sends failed. ${rulesCount} of them are rules, not bugs — ${attentionCount} need attention.`,
    ]);

    function renderReasonCard(r) {
      const isRed = r.actionable;
      const cardClass = isRed ? "rep-prob-card rep-prob-card--red" : "rep-prob-card rep-prob-card--grey";

      const ex = r.example;
      const exampleBlock = ex
        ? el("div.rep-prob-example", {}, [
            el("span", {}, [
              `Example: Chat with ${ex.contact || "Customer"} (${ex.detail || "Detail"})`,
            ]),
            el(
              "button.btn.btn--primary.btn--xs",
              {
                type: "button",
                onclick: () => {
                  dialog.close();
                  if (window.a7wa?.openConversation) {
                    window.a7wa.openConversation(ex.conversation_id);
                  }
                },
              },
              ["Open Chat"]
            ),
          ])
        : null;

      return el("div", { class: cardClass }, [
        el("div.rep-prob-top", {}, [
          el("div.rep-prob-title", {}, [r.label]),
          el("span.rep-chip", { class: isRed ? "rep-chip--red" : "rep-chip--amber" }, [`${r.count} failed`]),
        ]),
        el("div.rep-prob-meaning", {}, [r.meaning]),
        exampleBlock,
      ]);
    }

    const secAttention = attentionReasons.length
      ? el("div.rep-prob-sec", {}, [
          el("div.rep-prob-head", { style: "color: #ef4444;" }, [
            icon("alert", { size: 16 }),
            "NEEDS ATTENTION",
          ]),
          ...attentionReasons.map(renderReasonCard),
        ])
      : null;

    const secRules = rulesReasons.length
      ? el("div.rep-prob-sec", {}, [
          el("div.rep-prob-head", { style: "color: rgba(255,255,255,0.7);" }, [
            icon("shield", { size: 16 }),
            "NOT A FAULT",
          ]),
          ...rulesReasons.map(renderReasonCard),
        ])
      : null;

    contentArea.append(summaryLine, secAttention, secRules);
  }

  /* ----------------------------------------------------------- TEMPLATES */
  function renderTemplates(list) {
    if (!list || !list.length) {
      contentArea.append(el("div.tplc-empty", {}, ["Nothing happened in this period."]));
      return;
    }

    const tbody = el("tbody");
    for (const t of list) {
      const catClass = t.category === "MARKETING" ? "rep-chip rep-chip--amber" : "rep-chip rep-chip--green";
      const delRatePct = Math.round((t.delivery_rate || 0) * 100);
      const isLowRate = delRatePct < 50;

      const note = t.hit_daily_cap > 0
        ? el("div", { style: "font-size: 10px; color: #f59e0b; margin-top: 2px;" }, [
            "Meta's per-customer daily cap — the template is fine.",
          ])
        : null;

      tbody.append(
        el("tr", {}, [
          el("td", { style: "font-weight: 600;" }, [t.name, note]),
          el("td", {}, [el("span", { class: catClass }, [t.category])]),
          el("td", {}, [String(t.sent)]),
          el("td", {}, [String(t.delivered)]),
          el("td", {}, [String(t.read)]),
          el("td", { style: isLowRate ? "color: #f59e0b; font-weight: 600;" : "" }, [`${delRatePct}%`]),
          el("td", {}, [String(t.hit_daily_cap)]),
        ])
      );
    }

    const thead = el("thead", {}, [
      el("tr", {}, [
        el("th", {}, ["Template"]),
        el("th", {}, ["Category"]),
        el("th", {}, ["Sent"]),
        el("th", {}, ["Delivered"]),
        el("th", {}, ["Read"]),
        el("th", {}, ["Delivery rate"]),
        el("th", {}, ["Hit daily cap"]),
      ]),
    ]);

    const tableWrap = el("div.rep-table-wrap", {}, [el("table.rep-table", {}, [thead, tbody])]);
    contentArea.append(tableWrap);
  }

  // Boot
  renderHeaderControls();
  loadActiveTab();

  return dialog;
}

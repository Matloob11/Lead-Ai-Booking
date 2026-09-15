/**
 * Agents roster — Panel Admin + Official API / Linked phones access.
 */

import { catalog } from "../api/api.js";
import { clear, el, modal, toast } from "../core/dom.js";

function initials(name) {
  const parts = String(name || "?")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function accessToggle({ label, hint, checked, disabled, onChange }) {
  const input = el("input.akit-access__input", {
    type: "checkbox",
    checked: !!checked,
    disabled: !!disabled,
  });
  input.addEventListener("change", () => onChange(input));

  return el("label.akit-access", { className: disabled ? "akit-access is-disabled" : "akit-access" }, [
    el("span.akit-access__text", {}, [
      el("span.akit-access__label", {}, [label]),
      hint ? el("span.akit-access__hint", {}, [hint]) : null,
    ]),
    el("span.akit-access__switch", {}, [input, el("span.akit-access__track")]),
  ]);
}

export function openAgentsAdminModal({ me } = {}) {
  const body = el("div.modal__body.akit-agents", {}, [
    el("div.na-note", {}, ["Loading agents…"]),
  ]);
  const dialog = modal("Agents & access", body, { wide: true });

  let agents = [];
  let query = "";

  async function fetchAgents() {
    clear(body).append(el("div.na-note", {}, ["Loading agents…"]));
    try {
      agents = await catalog.agents();
      render();
    } catch (err) {
      clear(body).append(el("div.alert", {}, [`Failed to load agents: ${err.message}`]));
    }
  }

  async function patchAgent(agent, payload, input) {
    const previous = input.checked;
    input.disabled = true;
    try {
      const updated = await catalog.setAgentAccess(agent.id, payload);
      Object.assign(agent, {
        is_wa_admin: updated.is_wa_admin,
        is_manual_admin: updated.is_manual_admin,
        can_official_api: updated.can_official_api,
        can_linked_devices: updated.can_linked_devices,
        is_bitrix_admin: updated.is_bitrix_admin,
        community: updated.community,
        linked_session_count: updated.linked_session_count,
        numbers: updated.numbers,
      });
      toast("Access updated", "ok");
    } catch (err) {
      input.checked = !previous;
      toast(err.message || "Failed to update access", "err");
    } finally {
      input.disabled = false;
    }
  }

  function filtered() {
    const q = query.trim().toLowerCase();
    if (!q) return agents;
    return agents.filter((agent) => {
      const hay = [
        agent.display_name,
        agent.community,
        agent.username,
        agent.bitrix_user_id,
        String(agent.id),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }

  function renderRow(agent) {
    const isSelf = String(agent.id) === String(me?.id);
    const name = agent.display_name || agent.username || `Agent ${agent.id}`;
    const numberCount = agent.numbers?.length || 0;
    const linkedCount = agent.linked_session_count || 0;

    const officialToggle = accessToggle({
      label: "Official API",
      hint: "Cloud inbox",
      checked: agent.can_official_api !== false,
      onChange: (input) => patchAgent(agent, { can_official_api: input.checked }, input),
    });

    const linkedToggle = accessToggle({
      label: "Linked phones",
      hint: "QR / OpenWA",
      checked: agent.can_linked_devices !== false,
      onChange: (input) => patchAgent(agent, { can_linked_devices: input.checked }, input),
    });

    const communityInput = el("input.akit-agent__community", {
      type: "text",
      value: agent.community || "",
      placeholder: "Community — e.g. Damac Hills 2",
      maxlength: "120",
    });
    communityInput.addEventListener("change", async () => {
      const next = communityInput.value.trim();
      communityInput.disabled = true;
      try {
        const updated = await catalog.setAgentAccess(agent.id, { community: next });
        agent.community = updated.community || "";
        communityInput.value = agent.community;
        toast("Community saved", "ok");
        render();
      } catch (err) {
        communityInput.value = agent.community || "";
        toast(err.message || "Failed to save community", "err");
      } finally {
        communityInput.disabled = false;
      }
    });
    const adminInput = el("input", {
      type: "checkbox",
      checked: !!(agent.is_wa_admin || agent.is_manual_admin),
      disabled: isSelf,
    });
    adminInput.addEventListener("change", () => {
      if (isSelf) return;
      patchAgent(agent, { is_wa_admin: adminInput.checked }, adminInput);
    });

    return el("article.akit-agent", {}, [
      el("div.akit-agent__who", {}, [
        el("div.akit-agent__avatar", {}, [initials(name)]),
        el("div.akit-agent__meta", {}, [
          el("div.akit-agent__name", {}, [
            el("strong", {}, [name]),
            agent.community ? el("span.akit-pill.akit-pill--community", {}, [agent.community]) : null,
            isSelf ? el("span.akit-pill.akit-pill--you", {}, ["You"]) : null,
            agent.is_bitrix_admin
              ? el("span.akit-pill", { title: "Bitrix portal admin — cannot be changed here" }, [
                  "Portal Admin",
                ])
              : null,
          ]),
          el("div.akit-agent__sub", {}, [
            `Bitrix #${agent.bitrix_user_id || "—"} · ${numberCount} Official number${
              numberCount === 1 ? "" : "s"
            } · ${linkedCount} Linked phone${linkedCount === 1 ? "" : "s"}`,
          ]),
          communityInput,
        ]),
      ]),
      el("div.akit-agent__access", {}, [
        el("div.akit-agent__access-title", {}, ["Product access"]),
        el("div.akit-agent__toggles", {}, [officialToggle, linkedToggle]),
      ]),
      el("div.akit-agent__admin", {}, [
        el("label.akit-check", {}, [adminInput, "Panel Admin"]),
      ]),
    ]);
  }

  function render() {
    clear(body);

    const search = el("input.akit-agents__search", {
      type: "search",
      placeholder: "Search by name, community, or Bitrix id…",
      value: query,
      autocomplete: "off",
    });
    search.addEventListener("input", () => {
      query = search.value;
      render();
      const next = body.querySelector(".akit-agents__search");
      if (next) {
        next.focus();
        const len = next.value.length;
        next.setSelectionRange(len, len);
      }
    });

    const rows = filtered();
    const list = el("div.akit-agents__list");
    if (!rows.length) {
      list.append(el("div.akit-agents__empty", {}, ["No agents match this search."]));
    } else {
      for (const agent of rows) list.append(renderRow(agent));
    }

    body.append(
      el("header.akit-agents__head", {}, [
        el("div", {}, [
          el("h3.akit-agents__title", {}, ["Team access"]),
          el("p.akit-agents__lead", {}, [
            "Choose Official API, Linked phones, or both for each person. Community is the project they cover (Mudon Al Ranim, Damac Hills 2, …) — it shows next to their name. Panel Admin is separate — it unlocks Numbers, this roster, Linked phone agents, and New agent messages.",
          ]),
        ]),
        el("div.akit-agents__stats", {}, [
          el("span", {}, [`${agents.length} people`]),
        ]),
      ]),
      search,
      list
    );
  }

  fetchAgents();
  return dialog;
}

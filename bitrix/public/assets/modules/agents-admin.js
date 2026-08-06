/**
 * Agents & Admins Roster Management
 */

import { catalog } from "../api/api.js";
import { clear, el, modal, toast } from "../core/dom.js";
import { icon } from "../core/icons.js";

export function openAgentsAdminModal({ me } = {}) {
  const body = el("div.modal__body.na", {}, [el("div.na-note", {}, ["Loading agents list…"])]);
  const dialog = modal("Agents & Panel Admins", body, { wide: true });

  let agents = [];

  async function fetchAgents() {
    clear(body).append(el("div.na-note", {}, ["Loading agents list…"]));
    try {
      agents = await catalog.agents();
      render();
    } catch (err) {
      clear(body).append(el("div.alert", {}, [`Failed to load agents: ${err.message}`]));
    }
  }

  function render() {
    clear(body);
    const listContainer = el("div.na-rows");

    for (const agent of agents) {
      const isSelf = String(agent.id) === String(me.id);
      const isBitrixAdmin = agent.is_bitrix_admin;

      const toggleInput = el("input", {
        type: "checkbox",
        checked: agent.is_wa_admin || agent.is_manual_admin,
        disabled: isSelf,
        onchange: async () => {
          toggleInput.disabled = true;
          try {
            const updated = await catalog.setAgentAdmin(agent.id, toggleInput.checked);
            agent.is_wa_admin = updated.is_wa_admin;
            agent.is_manual_admin = updated.is_manual_admin;
          } catch (err) {
            toggleInput.checked = !toggleInput.checked;
            toast(err.message || "Failed to update admin rights", "err");
          } finally {
            if (!isSelf) toggleInput.disabled = false;
          }
        },
      });

      const card = el("div.na-row", { style: "padding: 12px; display: flex; align-items: center; justify-content: space-between; gap: 12px;" }, [
        el("div.na-who", { style: "flex: 1;" }, [
          el("div.na-title", { style: "font-weight: 600; font-size: 14px; display: flex; align-items: center; gap: 8px;" }, [
            agent.display_name || agent.username,
            isSelf ? el("span.na-badge.na-badge--ok", { style: "font-size: 10px;" }, ["You"]) : null,
          ]),
          el("div.na-phone", { style: "font-size: 11px; opacity: 0.7;" }, [
            `Bitrix #${agent.bitrix_user_id || agent.id} · ${agent.numbers?.length || 0} number(s) assigned`,
          ]),
        ]),
        el("div", { style: "display: flex; align-items: center; gap: 16px;" }, [
          isBitrixAdmin
            ? el("span.na-badge", { title: "Bitrix portal admin rights cannot be changed here", style: "opacity: 0.7;" }, ["Portal Admin (from Bitrix)"])
            : null,
          el("label", { style: "display: flex; align-items: center; gap: 8px; font-size: 12px; cursor: pointer;" }, [
            toggleInput,
            "Panel Admin",
          ]),
        ]),
      ]);

      listContainer.append(card);
    }

    body.append(listContainer);
  }

  fetchAgents();
  return dialog;
}

/**
 * Lead AI → Communities: the community packs (apps/leadai/assistant/communities.py).
 *
 * A pack is what the assistant knows of one community: the names customers
 * write it by (aliases), its sub-areas, the unit types sold or rented there, the
 * price bands it may quote when the inventory has no match, free facts lines,
 * the meeting point and the playbook knobs. Everyone with the Lead AI screen
 * reads the list; a panel admin edits a pack or adds one. International City
 * keeps its name and stays on: the assistant's own flow is built on it.
 *
 * The chats of a community read the pack on their next turn; nothing here sends.
 */

import { el, clear } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { leadAiApi } from "./api.js";
import { screenModal } from "./thread.js";

const UNITS = [
  ["studio", "Studio"],
  ["one_br", "One-bedroom"],
  ["two_plus", "Two bedrooms or more"],
  ["villa", "Villa"],
  ["townhouse", "Townhouse"],
  ["shop", "Shop"],
];
const DEALS = [
  ["rent", "To rent (a year)"],
  ["sale", "For sale"],
];
let communitiesDialog = null;

export function communitiesButton() {
  return el("button.lai-btn.lai-btn--ghost.lai-bar__communities", {
    type: "button",
    title: "The communities the assistant knows: names, sub-areas, units, price bands, the meeting point",
    onclick: () => openCommunitiesDialog(),
  }, [icon("globe", { size: 15 }), "Communities"]);
}

export function closeCommunitiesDialog() {
  communitiesDialog?.close();
}

export function openCommunitiesDialog() {
  if (communitiesDialog) return;
  const body = el("div.lai-com", {}, [el("p.lai-com__note", {}, ["Loading…"])]);
  const dialog = screenModal("Lead AI communities", body, {
    wide: true,
    onClose: () => {
      if (communitiesDialog === dialog) communitiesDialog = null;
    },
  });
  dialog.box.classList.add("lai-modal--communities");
  communitiesDialog = dialog;
  const state = { rows: [], canEdit: false, selected: null };

  leadAiApi.communities().then(
    (data) => {
      if (communitiesDialog !== dialog) return;
      state.rows = Array.isArray(data?.communities) ? data.communities : [];
      state.canEdit = Boolean(data?.can_edit);
      state.selected = state.rows[0]?.id ?? null;
      render();
    },
    (error) => {
      if (communitiesDialog !== dialog) return;
      clear(body).append(el("p.lai-com__note.lai-com__note--err", {}, [`Could not load the communities: ${error.message}`]));
    }
  );

  function current() {
    return state.rows.find((row) => row.id === state.selected) || null;
  }

  function render() {
    const list = el("div.lai-com__list", { role: "listbox", "aria-label": "Communities" }, state.rows.map((row) => listItem(row)));
    const side = el("aside.lai-com__side", {}, [
      el("div.lai-com__head", {}, [
        el("h3.lai-com__h", {}, [`${state.rows.length} communit${state.rows.length === 1 ? "y" : "ies"}`]),
        state.canEdit ? el("button.lai-btn.lai-btn--ghost.lai-btn--sm", { type: "button", onclick: () => addNew() }, [icon("plus", { size: 13 }), "Add"]) : null,
      ]),
      list,
    ]);
    const row = current();
    const main = el("div.lai-com__main", {}, [row ? form(row) : el("p.lai-com__note", {}, ["Pick a community on the left."])]);
    clear(body).append(side, main);
  }

  function listItem(row) {
    const live = Number(row.units_live || 0);
    return el("button.lai-com__item", {
      type: "button",
      role: "option",
      "aria-selected": row.id === state.selected ? "true" : "false",
      class: [row.id === state.selected ? "lai-com__item--on" : "", row.active ? "" : "lai-com__item--off"].filter(Boolean).join(" "),
      onclick: () => {
        state.selected = row.id;
        render();
      },
    }, [
      el("span.lai-com__item-name", {}, [row.name]),
      el("span.lai-com__item-sub", {}, [live ? `${live} unit${live === 1 ? "" : "s"} live` : "no units live", row.active ? "" : " · off"]),
    ]);
  }

  function addNew() {
    const name = window.prompt("The community's name (as Property Finder and the leads write it):", "");
    if (name === null) return;
    const clean = String(name).replace(/\s+/g, " ").trim();
    if (!clean) return;
    leadAiApi.createCommunity({ name: clean }).then(
      (row) => {
        state.rows = [...state.rows, row].sort((a, b) => String(a.name).localeCompare(String(b.name)));
        state.selected = row.id;
        render();
      },
      (error) => window.alert(error?.detail?.errors?.name || error.message || "Could not add the community.")
    );
  }

  /* ------------------------------------------------------------ the form */

  function form(row) {
    const fields = {};
    const note = el("p.lai-com__note", { role: "status" });
    const readOnly = !state.canEdit;

    function field(key, label, hint, { value = "", rows = 0, placeholder = "" } = {}) {
      const id = `lai-com-${key}`;
      const input = rows
        ? el("textarea.lai-set__input", { id, rows, value, placeholder, autocomplete: "off", readOnly })
        : el("input.lai-set__input", { id, type: "text", value, placeholder, autocomplete: "off", readOnly });
      const error = el("div.lai-set__err", { id: `${id}-error`, hidden: true });
      input.addEventListener("input", () => clearError(key));
      fields[key] = { input, error };
      return el("div.lai-set__field", {}, [el("label.lai-set__label", { for: id }, [label]), input, hint ? el("div.lai-set__hint", {}, [hint]) : null, error]);
    }

    function check(key, label, checked) {
      const id = `lai-com-${key}`;
      const input = el("input", { id, type: "checkbox", checked: Boolean(checked), disabled: readOnly });
      fields[key] = { input, error: el("div.lai-set__err", { hidden: true }) };
      return el("label.lai-com__check", { for: id }, [input, " ", label]);
    }

    function showError(key, message) {
      const item = fields[key];
      if (!item) return false;
      item.error.textContent = message;
      item.error.hidden = false;
      return true;
    }

    function clearError(key) {
      const item = fields[key];
      if (item) {
        item.error.hidden = true;
        item.error.textContent = "";
      }
    }

    const bandInputs = {};
    function bandRow(deal) {
      const cells = UNITS.filter(([unit]) => unit !== "shop").map(([unit, label]) => {
        const band = row.bands?.[deal]?.[unit] || {};
        const from = el("input.lai-set__input.lai-com__band", { type: "text", inputmode: "numeric", value: band.from ?? "", placeholder: "from", readOnly, "aria-label": `${label} ${deal} from` });
        const to = el("input.lai-set__input.lai-com__band", { type: "text", inputmode: "numeric", value: band.to ?? "", placeholder: "to", readOnly, "aria-label": `${label} ${deal} to` });
        bandInputs[`${deal}.${unit}`] = { from, to };
        return el("div.lai-com__band-cell", {}, [el("span.lai-com__band-l", {}, [label]), el("div.lai-com__band-pair", {}, [from, "–", to])]);
      });
      return el("div.lai-com__band-row", {}, [el("div.lai-com__band-deal", {}, [DEALS.find(([key]) => key === deal)[1]]), ...cells]);
    }
    const bandsError = el("div.lai-set__err", { hidden: true });
    fields.bands = { input: null, error: bandsError };

    const unitBoxes = UNITS.map(([unit, label]) => {
      const input = el("input", { type: "checkbox", value: unit, checked: (row.units || []).includes(unit), disabled: readOnly });
      return el("label.lai-com__check", {}, [input, " ", label]);
    });
    fields.units = { input: null, error: el("div.lai-set__err", { hidden: true }) };

    const meeting = el("select.lai-set__input", { id: "lai-com-meeting", disabled: readOnly }, [
      el("option", { value: "office", selected: row.meeting !== "onsite" }, ["Our office (the agent meets them there)"]),
      el("option", { value: "onsite", selected: row.meeting === "onsite" }, ["On site (an address below)"]),
    ]);
    fields.meeting = { input: meeting, error: el("div.lai-set__err", { hidden: true }) };

    const save = el("button.lai-btn.lai-btn--primary", { type: "submit", hidden: readOnly }, ["Save"]);

    function bandsValue() {
      const out = { rent: {}, sale: {} };
      for (const [key, pair] of Object.entries(bandInputs)) {
        const [deal, unit] = key.split(".");
        const from = pair.from.value.replace(/[,\s]/g, "");
        const to = pair.to.value.replace(/[,\s]/g, "");
        if (from || to) out[deal][unit] = { from, to };
      }
      return out;
    }

    function sameBands(a, b) {
      return JSON.stringify(a || {}) === JSON.stringify(b || {});
    }

    function normalBands(raw) {
      const out = {};
      for (const deal of ["rent", "sale"]) {
        for (const [unit, band] of Object.entries(raw?.[deal] || {})) {
          if (band && (band.from || band.to)) {
            out[deal] = out[deal] || {};
            out[deal][unit] = { from: Number(band.from), to: Number(band.to) };
          }
        }
      }
      return out;
    }

    function changes() {
      const out = {};
      const lines = (key) => fields[key].input.value.split(/\n/).map((item) => item.trim()).filter(Boolean);
      const aliases = fields.aliases.input.value.split(/[\n,;]+/).map((item) => item.trim().toLowerCase()).filter(Boolean);
      if (JSON.stringify(aliases) !== JSON.stringify(row.aliases || [])) out.aliases = aliases;
      const subs = lines("sub_areas");
      const rowSubs = (row.sub_areas || []).map((area) => (area.aliases?.length ? `${area.name} | ${area.aliases.join(", ")}` : area.name));
      if (JSON.stringify(subs) !== JSON.stringify(rowSubs)) out.sub_areas = subs;
      const units = unitBoxes.map((label) => label.querySelector("input")).filter((input) => input.checked).map((input) => input.value);
      if (JSON.stringify(units) !== JSON.stringify(row.units || [])) out.units = units;
      const bands = bandsValue();
      if (!sameBands(normalBands(bands), normalBands(row.bands))) out.bands = bands;
      const facts = fields.facts_text.input.value.split(/\n/).map((item) => item.trim()).filter(Boolean).join("\n");
      if (facts !== String(row.facts_text || "")) out.facts_text = facts;
      if (meeting.value !== String(row.meeting || "office")) out.meeting = meeting.value;
      const address = fields.meeting_address.input.value.replace(/\s+/g, " ").trim();
      if (address !== String(row.meeting_address || "")) out.meeting_address = address;
      const maps = fields.maps_url.input.value.trim();
      if (maps !== String(row.maps_url || "")) out.maps_url = maps;
      for (const key of ["shops", "call_first_sale", "active"]) {
        if (fields[key].input.checked !== Boolean(row[key])) out[key] = fields[key].input.checked;
      }
      return out;
    }

    async function submit(event) {
      event.preventDefault();
      if (save.disabled || readOnly) return;
      for (const key of Object.keys(fields)) clearError(key);
      note.textContent = "";
      const payload = changes();
      if (!Object.keys(payload).length) {
        note.textContent = "Nothing has changed.";
        return;
      }
      save.disabled = true;
      try {
        const next = await leadAiApi.updateCommunity(row.id, payload);
        state.rows = state.rows.map((item) => (item.id === next.id ? next : item));
        render();
        const fresh = body.querySelector(".lai-com__note");
        if (fresh) fresh.textContent = "Saved. The chats of this community read it on their next turn.";
      } catch (error) {
        const errors = error?.detail?.errors;
        let shown = false;
        if (errors && typeof errors === "object") {
          for (const [key, message] of Object.entries(errors)) {
            const top = String(key).split(".")[0];
            shown = showError(top, String(message)) || shown;
          }
        }
        note.textContent = shown ? "Please check the fields marked below." : error.message || "Could not save.";
        note.classList.add("lai-com__note--err");
      } finally {
        save.disabled = false;
      }
    }

    const live = Number(row.units_live || 0);
    return el("form.lai-com__form", { onsubmit: submit }, [
      el("div.lai-com__title", {}, [
        el("h3.lai-com__h", {}, [row.name]),
        el("span.lai-com__sub", {}, [live ? `${live} unit${live === 1 ? "" : "s"} live in the inventory` : "no units live: a home here still takes the old answer", row.active ? "" : " · switched off"]),
      ]),
      row.name === "International City"
        ? el("p.lai-com__note", {}, ["International City's bands live in AI settings (the residential facts); this pack carries its aliases, clusters and the shops knob."])
        : null,
      field("aliases", "Also written as", "How customers write it, one per line or comma-separated (the assistant reads these to tell the community).", { value: (row.aliases || []).join("\n"), rows: 3 }),
      field("sub_areas", "Sub-areas", "One per line: Name | alias, alias (clusters, phases, districts).", {
        value: (row.sub_areas || []).map((area) => (area.aliases?.length ? `${area.name} | ${area.aliases.join(", ")}` : area.name)).join("\n"),
        rows: 4,
      }),
      el("div.lai-set__field", {}, [el("span.lai-set__label", {}, ["Units sold or rented here"]), el("div.lai-com__checks", {}, unitBoxes), fields.units.error]),
      el("div.lai-set__field", {}, [
        el("span.lai-set__label", {}, ["Price bands (AED; a guide when the inventory has no match)"]),
        el("div.lai-com__bands", {}, DEALS.map(([deal]) => bandRow(deal))),
        bandsError,
      ]),
      field("facts_text", "Facts the assistant may quote", "One per line: what is true of this community (the chiller, the cheques, the handover date, …). Never a price here.", { value: row.facts_text || "", rows: 4 }),
      el("div.lai-set__field", {}, [el("label.lai-set__label", { for: "lai-com-meeting" }, ["Meeting point"]), meeting, fields.meeting.error]),
      field("meeting_address", "On-site address", "Only for an on-site meeting point; blank means our office.", { value: row.meeting_address || "" }),
      field("maps_url", "Maps link", "", { value: row.maps_url || "", placeholder: "https://maps.app.goo.gl/…" }),
      el("div.lai-com__checks", {}, [check("shops", "The shops flow applies here", row.shops), check("call_first_sale", "A buyer gets a sales call first", row.call_first_sale), check("active", "Active", row.active)]),
      note,
      el("div.lai-com__actions", {}, [save]),
    ]);
  }
}

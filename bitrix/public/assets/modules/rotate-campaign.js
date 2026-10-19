/**
 * Rotate campaign — aldardso across the locked numbers, 300 each.
 * The agent uploads the sheet and the header picture, then presses Start.
 * Nothing is sent until that click. Closing the window does not stop a send
 * that has already started.
 */

import { bulkCampaigns, catalog, inbox, rotateCampaigns } from "../api/api.js";
import { clear, el, formatBytes, modal, toast } from "../core/dom.js";
import { icon } from "../core/icons.js";

const LIVE = new Set(["running", "queued", "retrying"]);

function openRotateCampaign() {
  const body = el("div.rc-body");
  const dialog = modal("Rotate campaign", el("div.rc-shell", {}, [
    el("div.rc-tabs", {}, [
      tabButton("Send", "send"),
      tabButton("History", "history"),
    ]),
    body,
  ]), { wide: true });
  dialog.box.classList.add("modal__box--rotate");

  const state = {
    tab: "send",
    view: "form",
    pool: null,
    template: null,
    file: null,
    columns: [],
    phoneCol: 0,
    picture: null,
    pictureUrl: "",
    starting: false,
    progress: "",
    error: "",
    poll: null,
  };

  function tabButton(label, id) {
    return el("button.rc-tab", {
      type: "button",
      class: id === "send" ? "is-active" : "",
      "data-tab": id,
      onclick: () => {
        state.tab = id;
        state.view = id === "history" ? "list" : "form";
        markTabs();
        render();
      },
    }, [label]);
  }

  function markTabs() {
    dialog.box.querySelectorAll(".rc-tab").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.tab === state.tab);
    });
  }

  function add(nodes) {
    for (const node of nodes) {
      if (node) body.append(node);
    }
  }

  function render() {
    if (state.view !== "batch" && state.poll) {
      clearInterval(state.poll);
      state.poll = null;
    }
    clear(body);
    if (state.tab === "history" && state.view !== "batch") {
      renderHistory();
      return;
    }
    if (state.view === "batch") return;
    renderSend();
  }

  function renderSend() {
    const pool = state.pool;
    const ready = pool ? pool.numbers.filter((row) => row.can_send) : [];
    const waiting = pool ? pool.numbers.filter((row) => !row.can_send) : [];
    add([
      el("div.rc-layout", {}, [
        el("div.rc-form", {}, [
          el("p.rc-note", {}, [
            "Template is locked to aldardso. Each ready number takes 300 people, then the next number. Pending numbers are skipped until Meta approves them. A new chat from this campaign stays out of that number's agent inbox.",
          ]),
          pool
            ? el("div.rc-stats", {}, [
                stat(String(ready.length), "Ready numbers"),
                stat(String(pool.capacity), "Capacity"),
                stat(String(waiting.length), "Waiting"),
              ])
            : el("p.rc-note", {}, ["Loading numbers…"]),
          pool
            ? el("div.rc-pool", {}, pool.numbers.map((row) => el("div.rc-pool__row", { class: row.can_send ? "" : "rc-wait" }, [
                el("span", {}, [`+${row.phone}`]),
                el("span", {}, [row.agent ? `${row.label} · ${row.agent}` : (row.label || row.reason || "")]),
                el("span", {}, [row.can_send ? "Approved" : (row.template_status || "Skipped")]),
              ])))
            : null,
          el("label.rc-field", {}, [
            "Recipient file (Excel or CSV)",
            el("input", {
              type: "file",
              accept: ".xlsx,.csv,.xls",
              onchange: (event) => onFile(event.target.files?.[0]),
            }),
            state.file ? el("span", {}, [state.file.name]) : null,
          ]),
          state.columns.length
            ? el("label.rc-field", {}, [
                "Phone column",
                el("select", {
                  onchange: (event) => { state.phoneCol = Number(event.target.value); },
                }, state.columns.map((column, index) => el("option", {
                  value: String(index),
                  selected: index === state.phoneCol,
                }, [column.header || `Column ${index + 1}`]))),
              ])
            : null,
          el("label.rc-field", {}, [
            "Header picture",
            el("input", {
              type: "file",
              accept: "image/jpeg,image/png",
              onchange: (event) => onPicture(event.target.files?.[0]),
            }),
            state.picture ? el("span", {}, [`${state.picture.name} · ${formatBytes(state.picture.size)}`]) : null,
          ]),
          el("div.rc-actions", {}, [
            el("button.btn.btn--primary", {
              type: "button",
              disabled: state.starting,
              onclick: start,
            }, [state.starting ? "Starting…" : "Start campaign"]),
          ]),
          state.progress ? el("p.rc-note", {}, [state.progress]) : null,
          state.error ? el("p.rc-error", {}, [state.error]) : null,
        ]),
        previewCard(),
      ]),
    ]);
  }

  function previewCard() {
    const template = state.template;
    const bubble = el("div.rc-bubble");
    if (!template) {
      bubble.append(el("p.rc-note", {}, ["Loading the template…"]));
    } else {
      if (state.pictureUrl) {
        bubble.append(el("img.rc-bubble__image", { src: state.pictureUrl, alt: "Header picture" }));
      } else {
        bubble.append(el("div.rc-bubble__media", {}, ["Header picture appears here"]));
      }
      bubble.append(el("div.rc-bubble__body", {}, [template.body_text || ""]));
      if (template.footer_text) bubble.append(el("div.rc-bubble__footer", {}, [template.footer_text]));
    }
    const buttons = el("div.rc-btns", {}, (template?.buttons || []).slice(0, 3).map((button) => (
      el("div.rc-btn", {}, [button.text || "Button"])
    )));
    return el("aside.rc-phone", {}, [
      el("div.rc-phone__bar", {}, [template?.name || "aldardso"]),
      bubble,
      buttons,
    ]);
  }

  function stat(value, label) {
    return el("div.rc-stat", {}, [el("b", {}, [value]), el("span", {}, [label])]);
  }

  function onPicture(file) {
    if (state.pictureUrl) URL.revokeObjectURL(state.pictureUrl);
    state.picture = file || null;
    state.pictureUrl = file ? URL.createObjectURL(file) : "";
    if (state.view === "form") render();
  }

  async function onFile(file) {
    state.file = file || null;
    state.columns = [];
    state.error = "";
    if (!file) {
      render();
      return;
    }
    try {
      const inspected = await bulkCampaigns.inspect(file);
      state.columns = inspected.columns || [];
      if (Number.isInteger(inspected.guesses?.phone)) state.phoneCol = inspected.guesses.phone;
    } catch (error) {
      state.error = error.message;
    }
    render();
  }

  async function loadTemplate(numberId) {
    if (!numberId || state.template) return;
    try {
      const rows = await catalog.templates(numberId);
      const list = Array.isArray(rows) ? rows : (rows.templates || rows.results || []);
      state.template = list.find((row) => row.name === "aldardso" && row.language === "en") || null;
      if (state.view === "form") render();
    } catch {
      /* the form still works without the preview text */
    }
  }

  async function start() {
    state.error = "";
    state.progress = "";
    if (!state.file) {
      state.error = "Upload the recipient file.";
      render();
      return;
    }
    if (!state.picture) {
      state.error = "Choose the header picture.";
      render();
      return;
    }
    const ready = (state.pool?.numbers || []).filter((row) => row.can_send && row.id);
    if (!ready.length) {
      state.error = "No number has an approved aldardso yet.";
      render();
      return;
    }
    state.starting = true;
    render();
    const headerMediaIds = {};
    const skipped = [];
    try {
      for (let index = 0; index < ready.length; index += 1) {
        const row = ready[index];
        state.progress = `Uploading the picture to number ${index + 1} of ${ready.length}…`;
        render();
        try {
          const uploaded = await inbox.uploadMedia(state.picture, { numberId: row.id }).promise;
          headerMediaIds[String(row.id)] = uploaded.media_id;
        } catch (error) {
          skipped.push(`+${row.phone}: ${error.message}`);
        }
      }
      if (!Object.keys(headerMediaIds).length) {
        state.starting = false;
        state.progress = "";
        state.error = skipped.join(" ") || "No number accepted the header picture.";
        render();
        return;
      }
      state.progress = "Starting the campaign…";
      render();
      const batch = await rotateCampaigns.start({
        file: state.file,
        mapping: { phone: state.phoneCol },
        header_media_ids: headerMediaIds,
      });
      state.starting = false;
      state.progress = "";
      const missed = skipped.length ? ` ${skipped.length} number${skipped.length === 1 ? "" : "s"} skipped.` : "";
      toast(`Rotate campaign started. ${batch.total || 0} rows queued.${missed} You can close this window.`, skipped.length ? "err" : "ok");
      state.tab = "history";
      state.view = "batch";
      markTabs();
      drawBatch(batch);
      watch(batch.id);
    } catch (error) {
      state.starting = false;
      state.progress = "";
      state.error = error.message;
      state.view = "form";
      render();
    }
  }

  async function renderHistory() {
    body.append(el("p.rc-note", {}, ["Loading history…"]));
    try {
      const rows = await rotateCampaigns.history();
      const list = Array.isArray(rows) ? rows : [];
      if (state.view !== "list") return;
      clear(body);
      if (!list.length) {
        body.append(el("p.rc-note", {}, ["No rotate campaign yet. Start one from the Send tab. It keeps going here after you close this window."]));
        return;
      }
      add([
        el("p.rc-note", {}, ["A campaign keeps sending after you close this window. Open one to watch it."]),
        el("div.rc-history", {}, list.map((batch) => el("button.rc-batch", {
          type: "button",
          onclick: () => openBatch(batch.id),
        }, [
          batch.name,
          el("small", {}, [
            `${batch.status} · ${batch.counts?.sent || 0} sent · ${batch.counts?.failed || 0} failed · ${batch.counts?.pending || 0} pending`,
          ]),
        ]))),
      ]);
    } catch (error) {
      if (state.view !== "list") return;
      clear(body);
      body.append(el("p.rc-error", {}, [error.message]));
    }
  }

  async function openBatch(id) {
    state.tab = "history";
    state.view = "batch";
    markTabs();
    clear(body);
    body.append(el("p.rc-note", {}, ["Loading…"]));
    try {
      const batch = await rotateCampaigns.get(id);
      if (state.view !== "batch") return;
      drawBatch(batch);
      if (LIVE.has(batch.status)) watch(id);
    } catch (error) {
      if (state.view !== "batch") return;
      clear(body);
      body.append(el("p.rc-error", {}, [error.message]));
    }
  }

  function drawBatch(batch) {
    const counts = batch.counts || {};
    clear(body);
    const settled = !LIVE.has(batch.status);
    add([
      el("p.rc-note", {}, [
        settled
          ? `${batch.name} · ${batch.status}`
          : `${batch.name} is sending in the background. You can close this window.`,
      ]),
      (batch.skipped_numbers || []).length
        ? el("p.rc-note", {}, [
            `Skipped: ${(batch.skipped_numbers || []).map((row) => `+${row.phone}`).join(", ")}`,
          ])
        : null,
      el("div.rc-stats", {}, [
        stat(String(counts.sent || 0), "Sent"),
        stat(String(counts.failed || 0), "Failed"),
        stat(String(counts.pending || 0), "Pending"),
        stat(String(counts.retrying || 0), "Retrying"),
        stat(String(batch.leftover || 0), "Left out"),
      ]),
      el("div.rc-pool", {}, (batch.lanes || []).map((lane) => el("div.rc-pool__row", {}, [
        el("span", {}, [`+${lane.number || ""}`]),
        el("span", {}, [lane.label || ""]),
        el("span", {}, [`${lane.sent || 0} sent · ${lane.failed || 0} failed`]),
      ]))),
      el("div.rc-actions", {}, [
        el("button.btn", {
          type: "button",
          disabled: !settled,
          onclick: () => downloadFailed(batch.id),
        }, ["Download failed numbers"]),
        el("button.btn.btn--primary", {
          type: "button",
          disabled: !settled || !(counts.failed > 0),
          onclick: () => resend(batch.id),
        }, ["Send failed again"]),
        el("button.btn", {
          type: "button",
          onclick: () => {
            state.tab = "history";
            state.view = "list";
            markTabs();
            render();
          },
        }, ["Back"]),
      ]),
    ]);
  }

  function watch(id) {
    if (state.poll) clearInterval(state.poll);
    state.poll = setInterval(async () => {
      try {
        const batch = await rotateCampaigns.get(id);
        if (state.view === "batch") drawBatch(batch);
        if (!LIVE.has(batch.status)) {
          clearInterval(state.poll);
          state.poll = null;
          toast(`Rotate campaign ${batch.status}: ${batch.counts?.sent || 0} sent, ${batch.counts?.failed || 0} failed.`, batch.counts?.failed ? "err" : "ok");
        }
      } catch {
        /* keep the last numbers on screen */
      }
    }, 3000);
  }

  async function downloadFailed(id) {
    const response = await fetch(`/api/campaigns/rotate/${id}/failed.csv`, { credentials: "same-origin" });
    if (!response.ok) {
      toast("Could not download the failed numbers.", "err");
      return;
    }
    const blob = await response.blob();
    const link = el("a", { href: URL.createObjectURL(blob), download: `rotate-${id}-failed.csv` });
    link.click();
    URL.revokeObjectURL(link.href);
  }

  async function resend(id) {
    try {
      const batch = await rotateCampaigns.resend(id);
      toast("Failed numbers are sending again. You can close this window.", "ok");
      state.view = "batch";
      drawBatch(batch);
      watch(batch.id);
    } catch (error) {
      toast(error.message, "err");
    }
  }

  dialog.box.addEventListener("remove", () => {
    if (state.poll) clearInterval(state.poll);
    if (state.pictureUrl) URL.revokeObjectURL(state.pictureUrl);
  });

  rotateCampaigns.pool().then((pool) => {
    state.pool = pool;
    const first = (pool.numbers || []).find((row) => row.can_send && row.id);
    if (first) loadTemplate(first.id);
    if (state.view === "form") render();
  }).catch((error) => {
    state.error = error.message;
    if (state.view === "form") render();
  });
  render();
}

function injectMenuItem() {
  const menu = document.querySelector(".sidebar__menu");
  if (!menu) return false;
  if (menu.querySelector(".rc-menu-item")) return true;
  const item = el("button.btn.menu__item.rc-menu-item", {
    type: "button",
    onclick: () => openRotateCampaign(),
  }, [icon("file", { size: 16 }), "Rotate campaign"]);
  const after = [...menu.querySelectorAll(".menu__item")].find((button) => button.textContent.trim() === "Excel campaigns")
    || [...menu.querySelectorAll(".menu__item")].find((button) => button.textContent.trim() === "Campaign");
  if (after) after.after(item);
  else menu.append(item);
  return true;
}

if (!injectMenuItem()) {
  const observer = new MutationObserver(() => {
    if (injectMenuItem()) observer.disconnect();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
}

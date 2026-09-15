/**
 * Shared Media & Document Library UI
 */

import { inbox } from "../api/api.js";
import { clear, el, formatBytes, modal, toast } from "../core/dom.js";
import { icon } from "../core/icons.js";

export function openSharedLibraryModal({ onSelectAsset, isPicker = false } = {}) {
  const body = el("div.modal__body.na", {}, [el("div.na-note", {}, ["Loading shared library…"])]);
  const dialog = modal(isPicker ? "Select Document / Media to Send" : "Shared Media & Document Library", body, { wide: true });

  let assets = [];
  let filterKind = "";
  let searchTerm = "";

  const search = el("input.na-search", {
    type: "search",
    placeholder: "Search brochures, layouts, images…",
  });

  const kindSelect = el("select.na-picker", { style: "width: 140px;" }, [
    el("option", { value: "" }, ["All Types"]),
    el("option", { value: "document" }, ["Documents"]),
    el("option", { value: "image" }, ["Images"]),
    el("option", { value: "video" }, ["Videos"]),
  ]);

  const uploadBtn = el("button.btn.btn--primary.btn--sm", { type: "button" }, [
    icon("plus", { size: 14 }),
    " Upload Asset",
  ]);

  const listContainer = el("div.akit-asset-grid");

  const toolbar = el("div.na-toolbar", { style: "align-items: center;" }, [
    search,
    kindSelect,
    uploadBtn,
  ]);

  search.addEventListener("input", () => {
    searchTerm = search.value.trim().toLowerCase();
    render();
  });

  kindSelect.addEventListener("change", () => {
    filterKind = kindSelect.value;
    render();
  });

  uploadBtn.addEventListener("click", () => {
    openUploadSharedAssetModal({
      onUploaded: async () => {
        await fetchAssets();
      },
    });
  });

  async function fetchAssets() {
    clear(body).append(el("div.na-note", {}, ["Loading shared library…"]));
    try {
      assets = await inbox.sharedAssets();
      renderMain();
    } catch (err) {
      clear(body).append(el("div.alert", {}, [`Failed to load library: ${err.message}`]));
    }
  }

  function renderMain() {
    clear(body).append(toolbar, listContainer);
    render();
  }

  function render() {
    clear(listContainer);
    const filtered = assets.filter((a) => {
      const matchKind = !filterKind || a.kind === filterKind;
      const matchText =
        !searchTerm ||
        a.title.toLowerCase().includes(searchTerm) ||
        (a.file_name || "").toLowerCase().includes(searchTerm);
      return matchKind && matchText;
    });

    if (!filtered.length) {
      listContainer.append(el("div.tplc-empty", { style: "grid-column: 1/-1;" }, ["No shared assets found."]));
      return;
    }

    for (const asset of filtered) {
      const isImg = asset.kind === "image";
      const isVid = asset.kind === "video";
      const iconName = isImg ? "image" : isVid ? "video" : "fileText";

      const card = el("div.akit-asset-card", {}, [
        el("div.akit-asset-card__top", {}, [
          isImg && asset.url
            ? el("img.akit-asset-card__thumb", { src: asset.url, alt: "" })
            : el("div.akit-asset-card__icon", {}, [
                icon(iconName, { size: 22 }),
              ]),
          el("div.akit-row__main", {}, [
            el("div.akit-asset-card__title", {}, [asset.title]),
            el("div.akit-asset-card__meta", {}, [`${asset.file_name} · ${formatBytes(asset.size_bytes)}`]),
          ]),
        ]),
        el("div.akit-asset-card__foot", {}, [
          asset.url
            ? el("a.btn.btn--ghost.btn--sm", { href: asset.url, target: "_blank", rel: "noopener", title: "Preview / Download" }, [
                icon("eye", { size: 14 }),
              ])
            : null,
          el("button.btn.btn--danger.btn--sm", {
            type: "button",
            title: "Delete asset",
            onclick: async () => {
              try {
                await inbox.deleteSharedAsset(asset.id);
                toast(`Deleted "${asset.title}"`, "ok");
                await fetchAssets();
              } catch (err) {
                toast(`Delete failed: ${err.message}`, "err");
              }
            },
          }, [icon("trash", { size: 14 })]),
          isPicker || onSelectAsset
            ? el("button.btn.btn--primary.btn--sm", {
                type: "button",
                onclick: () => {
                  dialog.close();
                  onSelectAsset?.(asset);
                },
              }, ["Send in Chat"])
            : null,
        ]),
      ]);

      listContainer.append(card);
    }
  }

  fetchAssets();
  return dialog;
}

export function openUploadSharedAssetModal({ onUploaded } = {}) {
  const titleInput = el("input.field", { type: "text", placeholder: "e.g. A7 Luxury Villa Floorplan PDF" });
  const filePicker = el("input", { type: "file" });
  const statusEl = el("div.alert", { hidden: true });

  filePicker.addEventListener("change", () => {
    const file = filePicker.files?.[0];
    if (file && !titleInput.value.trim()) {
      titleInput.value = file.name.replace(/\.[^/.]+$/, "");
    }
  });

  const uploadBtn = el("button.btn.btn--primary", { type: "button" }, [
    icon("plus", { size: 14 }),
    " Upload to Shared Library",
  ]);

  const form = el("div.tplc-form", { style: "gap: 12px;" }, [
    el("label.tplc-field", {}, [el("span", {}, ["Document / File Title"]), titleInput]),
    el("label.tplc-field", {}, [el("span", {}, ["Select File (PDF, Brochure, Image, Video)"]), filePicker]),
    statusEl,
    el("div.tplc-actions", {}, [uploadBtn]),
  ]);

  const dialog = modal("Upload Shared Document / Media", form);

  uploadBtn.addEventListener("click", async () => {
    const file = filePicker.files?.[0];
    const title = titleInput.value.trim();
    if (!file) {
      statusEl.textContent = "Please select a file to upload.";
      statusEl.hidden = false;
      return;
    }

    uploadBtn.disabled = true;
    uploadBtn.textContent = "Uploading…";
    statusEl.hidden = true;

    try {
      await inbox.uploadSharedAsset(file, title);
      dialog.close();
      onUploaded?.();
    } catch (err) {
      uploadBtn.disabled = false;
      uploadBtn.replaceChildren(icon("plus", { size: 14 }), " Upload to Shared Library");
      statusEl.textContent = err.message || "Upload failed.";
      statusEl.hidden = false;
    }
  });

  return dialog;
}

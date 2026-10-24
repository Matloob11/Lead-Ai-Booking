(function () {
  if (window.A7BookingStageFieldsLoaded) {
    return;
  }
  window.A7BookingStageFieldsLoaded = true;

  var STAGE = "CONVERTED";
  var FIELDS = [
    "UF_CRM_A7_BOOKING_RENT_SALE",
    "UF_CRM_A7_COMMISSION_ZONE",
    "UF_CRM_A7_COMMISSION_DOC",
    "UF_CRM_A7_COMMISSION_STATUS",
    "UF_CRM_A7_COMMISSION_VOUCHER"
  ];
  var LABELS = {
    "Rent or Sale": true,
    "Commission Zone": true,
    "Commission Document": true,
    "Commission Status": true,
    "Commission Voucher No": true
  };

  var style = document.createElement("style");
  style.id = "a7-booking-stage-fields";
  style.textContent = FIELDS.map(function (name) {
    return '[data-cid="' + name + '"]';
  }).join(",") + ',[data-cid="a7_booking_fields"]{display:none !important}'
    + "body.a7-booking-stage-on " + FIELDS.map(function (name) {
      return '[data-cid="' + name + '"]';
    }).join(",body.a7-booking-stage-on ")
    + ",body.a7-booking-stage-on [data-cid=\"a7_booking_fields\"]{display:block !important}"
    + ".a7-booking-card-hide{display:none !important}";
  document.head.appendChild(style);

  function clean(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function editorStatus() {
    try {
      if (window.BX && BX.Crm && BX.Crm.EntityEditor && BX.Crm.EntityEditor.getDefault) {
        var editor = BX.Crm.EntityEditor.getDefault();
        var model = editor && editor.getModel ? editor.getModel() : null;
        var value = model && model.getField ? model.getField("STATUS_ID") : "";
        if (value) {
          return String(value);
        }
      }
    } catch (e) {}
    var current = document.querySelector(".crm-entity-section-status-step-item-current, .ui-stageflow-stage-item-current");
    if (current) {
      var id = current.getAttribute("data-id") || current.getAttribute("data-stage-id") || current.getAttribute("data-status-id") || "";
      if (id) {
        return id;
      }
      if (clean(current.textContent) === "Booking") {
        return STAGE;
      }
    }
    var select = document.querySelector('select[name="STATUS_ID"]');
    if (select && select.value) {
      return select.value;
    }
    return "";
  }

  function applyDetails() {
    var onDetails = /\/crm\/(?:lead|type\/1)\/details\//.test(location.pathname);
    if (!onDetails) {
      return;
    }
    document.body.classList.toggle("a7-booking-stage-on", editorStatus() === STAGE);
  }

  function isBookingColumn(column) {
    var id = column.getAttribute("data-id") || column.getAttribute("data-column-id") || "";
    if (id === STAGE) {
      return true;
    }
    var title = column.querySelector(".main-kanban-column-title, .crm-kanban-column-title");
    return !!(title && clean(title.textContent) === "Booking");
  }

  function applyKanban() {
    var items = document.querySelectorAll(".crm-kanban-item-fields-item, .crm-kanban-item-field");
    items.forEach(function (item) {
      var title = item.querySelector(".crm-kanban-item-fields-item-title, .crm-kanban-item-field-title");
      var label = clean(title ? title.textContent : item.getAttribute("data-title"));
      var code = item.getAttribute("data-field") || item.getAttribute("data-id") || "";
      var ours = !!LABELS[label] || FIELDS.indexOf(code) !== -1;
      if (!ours) {
        return;
      }
      var column = item.closest(".main-kanban-column, .crm-kanban-column");
      item.classList.toggle("a7-booking-card-hide", !(column && isBookingColumn(column)));
    });
  }

  function apply() {
    applyDetails();
    applyKanban();
  }

  apply();
  var tries = 0;
  var timer = setInterval(function () {
    tries += 1;
    apply();
    if (tries > 30) {
      clearInterval(timer);
    }
  }, 500);
  var observer = new MutationObserver(apply);
  observer.observe(document.body, { childList: true, subtree: true });
  if (window.BX && BX.addCustomEvent) {
    ["onCrmEntityUpdate", "Crm.EntityProgress.Saved", "Crm.EntityProgress.Change", "BX.Crm.EntityEditor:onLayout", "BX.UI.EntityEditor:onLayout", "Kanban.Grid:onRender"].forEach(function (name) {
      BX.addCustomEvent(window, name, apply);
    });
  }
})();

/* Local browser behaviour for the Swarm Call Dispatcher.
   Three small jobs, all external (no inline scripts anywhere):
   1. render UTC timestamps in the viewer's local timezone,
   2. show/hide password toggles,
   3. Enter submits the nearest Dash form, since Dash buttons are not native submits. */
(function () {
  "use strict";

  var timeFormatter = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  });

  function localise(element) {
    var iso = element.getAttribute("data-utc");
    if (!iso || element.getAttribute("data-localised") === "1") {
      return;
    }
    var moment = new Date(iso);
    if (isNaN(moment.getTime())) {
      element.setAttribute("data-localised", "1");
      return;
    }
    element.textContent = timeFormatter.format(moment);
    element.setAttribute("title", moment.toString());
    element.setAttribute("data-localised", "1");
  }

  function sweep(root) {
    if (!root || typeof root.querySelectorAll !== "function") {
      return;
    }
    var nodes = root.querySelectorAll("[data-utc]");
    for (var i = 0; i < nodes.length; i += 1) {
      localise(nodes[i]);
    }
  }

  var INPUT_VALUE_SETTER = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value"
  ).set;

  /* The Dash <select> bridge: the visible control is a real <select> with real
     option values; its choice is mirrored into a hidden Dash input that carries
     the field id, so server callbacks read one State value. */
  function wireSelect(select) {
    if (select.getAttribute("data-select-wired") === "1") {
      return;
    }
    select.setAttribute("data-select-wired", "1");
    var carrier = document.getElementById(select.getAttribute("data-select-sync"));
    if (carrier && carrier.value !== select.value) {
      select.value = carrier.value;
    }
    select.addEventListener("change", function (event) {
      var target = document.getElementById(
        event.currentTarget.getAttribute("data-select-sync")
      );
      if (!target) {
        return;
      }
      INPUT_VALUE_SETTER.call(target, event.currentTarget.value);
      target.dispatchEvent(new Event("input", { bubbles: true }));
      target.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }

  function wireSelects(root) {
    if (!root || typeof root.querySelectorAll !== "function") {
      return;
    }
    var selects = root.querySelectorAll("select[data-select-sync]");
    for (var i = 0; i < selects.length; i += 1) {
      wireSelect(selects[i]);
    }
  }

  function watchTimestamps() {
    sweep(document);
    var observer = new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i += 1) {
        var added = records[i].addedNodes;
        for (var j = 0; j < added.length; j += 1) {
          var node = added[j];
          if (node.nodeType === 1) {
            localise(node);
            sweep(node);
            wireSelects(node);
          }
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  function wirePasswordToggles(root) {
    var buttons = root.querySelectorAll("[data-pw-toggle]");
    for (var i = 0; i < buttons.length; i += 1) {
      var button = buttons[i];
      if (button.getAttribute("data-wired") === "1") {
        continue;
      }
      button.setAttribute("data-wired", "1");
      button.addEventListener("click", function (event) {
        var target = document.getElementById(event.currentTarget.getAttribute("data-pw-toggle"));
        if (!target) {
          return;
        }
        var showing = target.getAttribute("type") === "text";
        target.setAttribute("type", showing ? "password" : "text");
        event.currentTarget.setAttribute("aria-pressed", showing ? "false" : "true");
        event.currentTarget.setAttribute("aria-label", showing ? "Show password" : "Hide password");
        event.currentTarget.textContent = showing ? "Show" : "Hide";
      });
    }
  }

  function submitFor(target) {
    var scope = target.closest("[data-enter-form]") || target.closest("form") || document;
    return scope.querySelector("[data-enter-submit]");
  }

  function wireEnterToSubmit(root) {
    if (root.getAttribute && root.getAttribute("data-enter-wired") === "1") {
      return;
    }
    if (root.setAttribute) {
      root.setAttribute("data-enter-wired", "1");
    }
    root.addEventListener("keydown", function (event) {
      if (event.key !== "Enter") {
        return;
      }
      var target = event.target;
      var tag = target.tagName;
      if (tag === "TEXTAREA" || tag === "BUTTON") {
        return;
      }
      if (tag !== "INPUT" && tag !== "SELECT") {
        return;
      }
      var button = submitFor(target);
      if (!button || button.disabled) {
        return;
      }
      event.preventDefault();
      button.click();
    });
  }

  var TAB_SLUGS = ["reports", "dispatch", "volunteers", "outcomes"];

  function syncTabUrl() {
    var selected = document.querySelector(".swarm-tab--selected");
    if (!selected) {
      return;
    }
    var slug = selected.textContent.trim().toLowerCase();
    if (TAB_SLUGS.indexOf(slug) === -1) {
      return;
    }
    var current = new URL(window.location.href);
    if (current.searchParams.get("tab") === slug) {
      return;
    }
    current.searchParams.set("tab", slug);
    window.history.replaceState(null, "", current.toString());
  }

  function start() {
    watchTimestamps();
    wirePasswordToggles(document);
    wireEnterToSubmit(document);
    wireSelects(document);
    syncTabUrl();
    /* Dash re-mounts content, so re-wire the controls after every repaint. */
    var observer = new MutationObserver(function () {
      wirePasswordToggles(document);
      wireSelects(document);
      syncTabUrl();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();

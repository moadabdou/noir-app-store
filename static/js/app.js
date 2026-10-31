/* NOIR / apps - progressive enhancement only. The site works without JS. */
(function () {
  "use strict";

  var STORE_KEY = "noir.saved.v1";

  function $(selector, scope) {
    return (scope || document).querySelector(selector);
  }
  function $$(selector, scope) {
    return Array.prototype.slice.call((scope || document).querySelectorAll(selector));
  }

  function readSaved() {
    try {
      var raw = window.localStorage.getItem(STORE_KEY);
      var parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      return [];
    }
  }

  function writeSaved(list) {
    try {
      window.localStorage.setItem(STORE_KEY, JSON.stringify(list));
    } catch (err) {
      /* storage disabled - the page still works, bookmarks just do not persist */
    }
  }

  var toastEl = null;
  var toastTimer = null;

  function toast(message) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "toast";
      toastEl.setAttribute("role", "status");
      toastEl.setAttribute("aria-live", "polite");
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = message;
    toastEl.classList.add("is-visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      toastEl.classList.remove("is-visible");
    }, 2200);
  }

  /* ------------------------------------------------------------ mobile nav */

  function initNav() {
    var toggle = $("#nav-toggle");
    var nav = $("#nav");
    if (!toggle || !nav) return;

    function setOpen(open) {
      document.body.classList.toggle("nav-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    }

    toggle.addEventListener("click", function () {
      setOpen(!document.body.classList.contains("nav-open"));
    });

    nav.addEventListener("click", function (event) {
      if (event.target.closest("a")) setOpen(false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") setOpen(false);
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > 900) setOpen(false);
    });
  }

  /* -------------------------------------------------------------- bookmark */

  function updateSaveButtons(slug, saved) {
    $$('[data-save-slug]').forEach(function (button) {
      if (button.getAttribute("data-save-slug") !== slug) return;
      button.classList.toggle("is-saved", saved);
      var label = button.getAttribute("data-save-label");
      if (label) {
        button.textContent = saved ? "Saved" : "Save";
      } else {
        button.textContent = saved ? "Saved" : "Save";
      }
    });
  }

  function updateBadge() {
    var badge = $("#saved-count");
    if (!badge) return;
    var count = readSaved().length;
    badge.textContent = String(count);
    badge.hidden = count === 0;
  }

  function initSave() {
    var saved = readSaved();
    $$('[data-save-slug]').forEach(function (button) {
      var slug = button.getAttribute("data-save-slug");
      if (saved.indexOf(slug) !== -1) {
        button.classList.add("is-saved");
        if (button.hasAttribute("data-save-label")) button.textContent = "Saved";
      }
      button.addEventListener("click", function (event) {
        if (button.tagName === "A") {
          event.preventDefault();
        }
        var list = readSaved();
        var index = list.indexOf(slug);
        var name = button.getAttribute("data-save-name") || slug;
        if (index === -1) {
          list.push(slug);
          toast(name + " saved to your list");
        } else {
          list.splice(index, 1);
          toast(name + " removed from your list");
        }
        writeSaved(list);
        updateSaveButtons(slug, index === -1);
        updateBadge();
        if (document.body.classList.contains("page-saved")) renderSaved();
      });
    });
    updateBadge();
  }

  /* ------------------------------------------------------------ card markup */

  function starsMarkup(rating) {
    var full = Math.floor(rating);
    var rest = rating - full >= 0.4 ? 1 : 0;
    var empty = 5 - full - rest;
    var out = '<span class="stars" aria-hidden="true">';
    out += '<span class="stars__on">★</span>';
    out += '<span class="stars__half">★</span>';
    out += '<span class="stars__off">★</span>';
    out += "</span>";
    return out;
  }

  function cardMarkup(app, categoryName) {
    var isMod = app.isMod || app.type === "mod";
    var kind = isMod ? "Mod" : (app.type === "game" ? "Game" : "App");
    var name = categoryName || app.categoryName || app.category;
    var search = (app.name + " " + app.developer + " " + name + " " + (app.tagline || "")).toLowerCase();
    var flags = "";
    if (isMod) flags += '<span class="card__flag card__flag--mod">MOD</span>';
    if (app.isDemo) flags += '<span class="card__flag card__flag--demo">DEMO</span>';
    return (
      '<a class="card" href="/app/' + encodeURIComponent(app.slug) + '" data-slug="' + app.slug + '"' +
      ' data-name="' + app.name.toLowerCase() + '" data-type="' + app.type + '"' +
      ' data-category="' + app.category + '" data-rating="' + app.rating + '"' +
      ' data-updated="' + app.updated + '" data-size="' + app.size + '"' +
      ' data-mod="' + (isMod ? 1 : 0) + '"' +
      ' data-search="' + search.replace(/"/g, "&quot;") + '">' +
      '<div class="card__top">' +
      '<img class="card__icon" src="' + app.icon + '" alt="' + app.name + ' icon" width="64" height="64" loading="lazy">' +
      '<span class="card__kind">' + kind + "</span>" +
      flags +
      "</div>" +
      '<h3 class="card__name">' + app.name + "</h3>" +
      '<p class="card__dev">' + app.developer + "</p>" +
      '<div class="card__foot">' +
      '<span class="pill pill--rating">' + starsMarkup(app.rating) + "<b>" + app.rating + "</b></span>" +
      '<span class="pill">' + app.size + "</span>" +
      "</div>" +
      '<div class="card__tags"><span class="tag">' + name + "</span>" +
      '<span class="tag">' + (app.android || "") + "</span></div>" +
      "</a>"
    );
  }

  /* --------------------------------------------------------------- catalogue */

  function parseSize(size) {
    var match = /([\d.]+)\s*(KB|MB|GB)/i.exec(size || "0 MB");
    if (!match) return 0;
    var value = parseFloat(match[1]);
    var unit = match[2].toUpperCase();
    if (unit === "GB") return value * 1000;
    if (unit === "KB") return value / 1000;
    return value;
  }

  function initCatalog() {
    var grid = $("#catalog-grid");
    var form = $("#catalog-form");
    if (!grid || !form) return;

    var chips = $$("#filter-chips .chip");
    var categoryNames = {};
    chips.forEach(function (chip) {
      var slug = (chip.getAttribute("href") || "").split("/category/")[1];
      if (!slug) return;
      categoryNames[slug] = chip.textContent.replace(/\d+$/, "").trim();
    });

    var params = new URLSearchParams(window.location.search);
    var state = {
      type: form.getAttribute("data-type") || "all",
      category: form.getAttribute("data-category") || "",
      q: params.get("q") || "",
      sort: params.get("sort") || "popular",
      mods: form.getAttribute("data-mods") === "1",
      page: parseInt(params.get("page") || "1", 10) || 1
    };

    var input = $("#catalog-search");
    var select = $("#catalog-sort");
    var countEl = $("#result-count");
    var emptyEl = $("#empty-state");
    var hintEl = $("#filter-hint");
    var pagerEl = $("#catalog-pager");
    var pending = 0;

    if (input && state.q) input.value = state.q;
    if (select) select.value = state.sort;

    function apiUrl() {
      var query = new URLSearchParams();
      query.set("type", state.type);
      query.set("sort", state.sort);
      query.set("page", String(state.page));
      if (state.q) query.set("q", state.q);
      if (state.category) query.set("category", state.category);
      if (state.mods) query.set("mods", "1");
      return "/api/apps?" + query.toString();
    }

    function pagerMarkup(meta) {
      if (!meta || meta.pages <= 1) return "";
      var numbers = "";
      for (var number = 1; number <= meta.pages; number += 1) {
        numbers += '<a class="pager__page' + (number === meta.page ? " is-active" : "") +
          '" href="#" data-page="' + number + '"' +
          (number === meta.page ? ' aria-current="page"' : "") + ">" + number + "</a>";
      }
      var prev = meta.has_prev
        ? '<a class="pager__step" href="#" data-page="' + (meta.page - 1) + '">Previous</a>'
        : '<span class="pager__step is-off">Previous</span>';
      var next = meta.has_next
        ? '<a class="pager__step" href="#" data-page="' + (meta.page + 1) + '">Next</a>'
        : '<span class="pager__step is-off">Next</span>';
      return prev + '<span class="pager__pages">' + numbers + "</span>" + next +
        '<span class="pager__count">Page ' + meta.page + " of " + meta.pages + "</span>";
    }

    function syncUrl(replace) {
      var next = new URLSearchParams();
      if (state.type && state.type !== "app") next.set("type", state.type);
      if (state.q) next.set("q", state.q);
      if (state.category) next.set("category", state.category);
      if (state.mods) next.set("mods", "1");
      if (state.sort && state.sort !== "popular") next.set("sort", state.sort);
      if (state.page > 1) next.set("page", String(state.page));
      var url = window.location.pathname + (next.toString() ? "?" + next.toString() : "");
      if (replace) window.history.replaceState({}, "", url);
      else window.history.pushState({}, "", url);
    }

    function render(items, meta) {
      grid.innerHTML = items.map(function (app) {
        return cardMarkup(app, categoryNames[app.category] || app.categoryName);
      }).join("");

      if (countEl) {
        var noun = meta.total === 1 ? "result" : "results";
        var label = "<b>" + meta.total + "</b> " + noun;
        if (state.category) label += " in " + (categoryNames[state.category] || state.category);
        else if (state.mods) label += " in Mods";
        if (state.q) label += " for \u201c" + state.q + "\u201d";
        countEl.innerHTML = label;
      }
      if (hintEl) {
        hintEl.hidden = !(state.q || state.category || state.mods);
        hintEl.textContent = state.q
          ? "Filtering live \u2014 press Apply to search the whole catalogue."
          : "Showing a filtered view \u2014 press Apply to keep it in the address bar.";
      }
      if (emptyEl) emptyEl.hidden = meta.total !== 0;
      if (pagerEl) pagerEl.innerHTML = pagerMarkup(meta);
    }

    function load(pushUrl) {
      var token = ++pending;
      fetch(apiUrl(), { headers: { Accept: "application/json" } })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          if (token !== pending) return;
          render(data.items || [], data);
          if (pushUrl !== false) syncUrl(true);
        })
        .catch(function () {
          if (token !== pending) return;
          grid.innerHTML = "";
        });
    }

    if (input) {
      var timer = null;
      input.addEventListener("input", function () {
        window.clearTimeout(timer);
        timer = window.setTimeout(function () {
          state.q = input.value.trim();
          state.page = 1;
          load();
        }, 160);
      });
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          form.submit();
        }
      });
    }

    if (select) {
      select.addEventListener("change", function () {
        state.sort = select.value;
        state.page = 1;
        load();
      });
    }

    chips.forEach(function (chip) {
      if (chip.hasAttribute("data-mods-filter")) {
        chip.addEventListener("click", function (event) {
          event.preventDefault();
          state.mods = !state.mods;
          state.page = 1;
          chips.forEach(function (other) {
            if (other.hasAttribute("data-mods-filter")) {
              other.classList.toggle("is-active", state.mods);
            }
          });
          load();
        });
        return;
      }
      chip.addEventListener("click", function (event) {
        event.preventDefault();
        var slug = (chip.getAttribute("href") || "").split("/category/")[1] || "";
        state.category = state.category === slug ? "" : slug;
        state.page = 1;
        chips.forEach(function (other) {
          var otherSlug = (other.getAttribute("href") || "").split("/category/")[1] || "";
          other.classList.toggle("is-active", otherSlug === state.category);
        });
        load();
      });
    });

    $$(".tab").forEach(function (tab) {
      tab.addEventListener("click", function (event) {
        var href = tab.getAttribute("href") || "";
        var target = new URL(href, window.location.origin);
        if (target.pathname !== "/apps" && target.pathname !== "/games") return;
        event.preventDefault();
        state.type = target.searchParams.get("type") || (target.pathname === "/games" ? "game" : "app");
        state.category = "";
        state.page = 1;
        $$(".tab").forEach(function (other) { other.classList.remove("is-active"); });
        tab.classList.add("is-active");
        chips.forEach(function (chip) { chip.classList.remove("is-active"); });
        load();
      });
    });

    if (pagerEl) {
      pagerEl.addEventListener("click", function (event) {
        var link = event.target.closest("[data-page]");
        if (!link) return;
        event.preventDefault();
        state.page = parseInt(link.getAttribute("data-page"), 10) || 1;
        load();
        var top = grid.getBoundingClientRect().top + window.pageYOffset - 96;
        window.scrollTo({ top: top, behavior: "smooth" });
      });
    }

    window.addEventListener("popstate", function () {
      var next = new URLSearchParams(window.location.search);
      state.q = next.get("q") || "";
      state.category = next.get("category") || "";
      state.mods = next.get("mods") === "1";
      state.sort = next.get("sort") || "popular";
      state.page = parseInt(next.get("page") || "1", 10) || 1;
      if (input) input.value = state.q;
      if (select) select.value = state.sort;
      load(false);
    });

    load(false);
  }

  /* ------------------------------------------------------------- saved page */

  function renderSaved() {
    var grid = $("#saved-grid");
    var empty = $("#saved-empty");
    var dataEl = $("#catalog-data");
    if (!grid || !dataEl) return;
    var catalog;
    try {
      catalog = JSON.parse(dataEl.textContent);
    } catch (err) {
      return;
    }
    var saved = readSaved();
    var list = catalog.filter(function (app) { return saved.indexOf(app.slug) !== -1; });
    grid.innerHTML = list.map(function (app) {
      return cardMarkup(app, app.category);
    }).join("");
    if (empty) empty.hidden = list.length !== 0;
    grid.hidden = list.length === 0;
  }

  function initSavedPage() {
    if (!$("#saved-grid")) return;
    renderSaved();
    var clear = $("#clear-saved");
    if (clear) {
      clear.addEventListener("click", function () {
        writeSaved([]);
        updateBadge();
        renderSaved();
        toast("Saved list cleared");
      });
    }
  }

  /* -------------------------------------------------------------- lightbox */

  function initLightbox() {
    var wrap = $("[data-lightbox]");
    if (!wrap) return;
    var shots = $$(".shot img", wrap);
    if (!shots.length) return;
    var overlay = null;

    function close() {
      if (overlay) {
        overlay.remove();
        overlay = null;
        document.body.style.overflow = "";
      }
    }

    function open(index) {
      close();
      overlay = document.createElement("div");
      overlay.className = "lightbox";
      var img = document.createElement("img");
      img.src = shots[index].src;
      img.alt = shots[index].alt || "Screenshot";
      var closeBtn = document.createElement("button");
      closeBtn.className = "lightbox__close";
      closeBtn.type = "button";
      closeBtn.setAttribute("aria-label", "Close screenshot");
      closeBtn.textContent = "×";
      var counter = document.createElement("span");
      counter.className = "lightbox__count";
      counter.textContent = index + 1 + " / " + shots.length;
      overlay.appendChild(img);
      overlay.appendChild(closeBtn);
      overlay.appendChild(counter);
      overlay.addEventListener("click", function (event) {
        if (event.target === overlay || event.target === closeBtn) close();
      });
      document.body.appendChild(overlay);
      document.body.style.overflow = "hidden";
      closeBtn.focus();
    }

    shots.forEach(function (shot, index) {
      shot.addEventListener("click", function () { open(index); });
      shot.parentNode.setAttribute("tabindex", "0");
      shot.parentNode.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open(index);
        }
      });
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") close();
    });
  }

  /* ------------------------------------------------------------------ share */

  function initShare() {
    $$("[data-share]").forEach(function (button) {
      button.addEventListener("click", function () {
        var url = window.location.href;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(url).then(function () {
            toast("Link copied to clipboard");
          }).catch(function () {
            toast(url);
          });
        } else {
          toast(url);
        }
      });
    });
  }

  /* ------------------------------------------------------------------- init */

  document.addEventListener("DOMContentLoaded", function () {
    initNav();
    initSave();
    initCatalog();
    initSavedPage();
    initLightbox();
    initShare();
  });
})();

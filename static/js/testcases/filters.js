/**
 * Фильтры и работа с тегами.
 * Зависимости: namespace.js, common/utils.js
 */
(function() {
  'use strict';

  const { utils } = window.TestOps;

  function setupTagDropdown() {
    const root = document.getElementById("tags-filter-root");
    const pageRoot = document.getElementById("testcases-root");
    if (!root || !pageRoot) return;

    const toggle = document.getElementById("tags-toggle");
    const dropdown = document.getElementById("tags-dropdown");
    const listEl = document.getElementById("tags-list");
    const searchInput = document.getElementById("tags-search");
    const clearBtn = document.getElementById("tags-clear");
    const hidden = document.getElementById("tags-hidden");
    const summary = document.getElementById("tags-summary");

    let tags = [];
    try {
      const raw = pageRoot.dataset.allTags || "[]";
      tags = JSON.parse(raw).map((n) => ({ name: n }));
    } catch (e) {
      tags = [];
    }

    const initialCsv =
      pageRoot.dataset.selectedTags ||
      (hidden && hidden.value ? hidden.value : "");
    const initialSelectedArr = utils.splitCsv(initialCsv);
    let selected = new Set(initialSelectedArr);

    function updateSummary() {
      summary.textContent = "Теги";
    }

    function renderList(filterText = "") {
      listEl.innerHTML = "";
      const lower = (filterText || "").toLowerCase();

      if (!tags || tags.length === 0) {
        listEl.innerHTML = '<div class="text-xs text-gray-500">Теги недоступны</div>';
        return;
      }

      const filtered = tags.filter((t) =>
        (t.name || "").toLowerCase().includes(lower)
      );
      if (filtered.length === 0) {
        listEl.innerHTML = '<div class="text-xs text-gray-500">Теги не найдены</div>';
        return;
      }

      filtered.forEach((t, idx) => {
        const safeName = (t.name || "").replace(/"/g, "&quot;");
        const id = "tag-cb-" + idx;
        const div = document.createElement("div");
        div.className = "flex items-center gap-2";
        const checked = selected.has(t.name) ? "checked" : "";
        div.innerHTML = `<label class="flex items-center gap-2 w-full cursor-pointer">
            <input type="checkbox" class="tag-checkbox" data-name="${safeName}" id="${id}" ${checked}/>
            <span class="truncate">${t.name}</span>
          </label>`;
        listEl.appendChild(div);
      });
    }

    toggle.addEventListener("click", function (e) {
      e.stopPropagation();
      dropdown.classList.toggle("hidden");
      if (!dropdown.classList.contains("hidden")) {
        searchInput.focus();
        renderList(searchInput.value || "");
      }
    });

    searchInput.addEventListener("input", function () {
      renderList(this.value || "");
    });

    async function applyAndNavigate() {
      const arr = Array.from(selected);
      hidden.value = arr.join(",");
      const params = new URLSearchParams(window.location.search);
      if (arr.length) params.set("tags", arr.join(","));
      else params.delete("tags");
      params.delete("cursor");

      const targetUrl = window.location.pathname + "?" + params.toString();

      try {
        const res = await fetch(targetUrl, { credentials: "same-origin" });
        if (!res.ok) {
          throw new Error(`Request failed: ${res.status}`);
        }
        const html = await res.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");

        const incomingTbody = doc.querySelector("#cases-tbody");
        const incomingMeta = doc.querySelector("#meta-count");
        const incomingPrev = doc.querySelector("#prev-link");
        const incomingNext = doc.querySelector("#next-link");
        const incomingHidden = doc.querySelector("#tags-hidden");

        const tbody = document.querySelector("#cases-tbody");
        if (incomingTbody && tbody) {
          tbody.innerHTML = incomingTbody.innerHTML;
        }

        const meta = document.querySelector("#meta-count");
        if (incomingMeta && meta) {
          meta.textContent = incomingMeta.textContent;
        }

        const prev = document.querySelector("#prev-link");
        if (prev) {
          if (incomingPrev && incomingPrev.href) {
            prev.href = incomingPrev.href;
            prev.classList.remove("hidden");
          } else {
            prev.remove();
          }
        } else if (incomingPrev && incomingPrev.href) {
          const pag = document.querySelector("#pagination");
          if (pag) {
            pag.insertAdjacentElement("afterbegin", incomingPrev);
          }
        }

        const next = document.querySelector("#next-link");
        if (next) {
          if (incomingNext && incomingNext.href) {
            next.href = incomingNext.href;
            next.classList.remove("hidden");
          } else {
            next.remove();
          }
        } else if (incomingNext && incomingNext.href) {
          const pag = document.querySelector("#pagination");
          if (pag) {
            pag.insertAdjacentElement("beforeend", incomingNext);
          }
        }

        // сохраняем hidden значение для будущих сабмитов формы
        if (incomingHidden && hidden) {
          hidden.value = incomingHidden.value || "";
        }

        window.history.replaceState({}, "", targetUrl);
      } catch (err) {
        console.error("Не удалось обновить список по тегам:", err);
        // fallback — перезагрузить страницу
        window.location.href = targetUrl;
      }
    }

    listEl.addEventListener("change", function (e) {
      const cb = e.target.closest(".tag-checkbox");
      if (!cb) return;
      const name = cb.dataset.name;
      if (cb.checked) selected.add(name);
      else selected.delete(name);
      updateSummary();
      applyAndNavigate();
    });

    // Не закрываем дропдаун при клике внутри
    dropdown.addEventListener("click", (e) => e.stopPropagation());
    listEl.addEventListener("click", (e) => e.stopPropagation());
    searchInput.addEventListener("click", (e) => e.stopPropagation());

    clearBtn.addEventListener("click", function () {
      selected.clear();
      hidden.value = "";
      renderList(searchInput.value || "");
      updateSummary();
      const params = new URLSearchParams(window.location.search);
      params.delete("tags");
      params.delete("cursor");
      window.location.search = params.toString();
    });

    document.addEventListener("click", function (e) {
      if (!root.contains(e.target)) dropdown.classList.add("hidden");
    });

    updateSummary();
    renderList("");
  }

  function setupAutoSubmitFilters() {
    document.querySelectorAll("[data-auto-submit-filter]").forEach((el) => {
      el.addEventListener("change", () => {
        const form = el.closest("form");
        if (form) {
          form.submit();
        }
      });
    });
  }

  // Экспорт
  window.TestOps.filters = {
    setupTagDropdown,
    setupAutoSubmitFilters,
  };
})();


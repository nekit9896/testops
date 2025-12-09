(() => {
  const api = {
    async request(url, { method = "GET", body, headers = {} } = {}) {
      const opts = {
        method,
        credentials: "same-origin",
        headers: {
          ...(body ? { "Content-Type": "application/json" } : {}),
          ...headers,
        },
        body,
      };
      const res = await fetch(url, opts);
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        const message = text || `Request failed (${res.status})`;
        throw new Error(message);
      }
      const ct = res.headers.get("content-type") || "";
      if (ct.includes("application/json")) {
        return res.json();
      }
      return res.text();
    },
  };

  function splitCsv(value = "") {
    return String(value)
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
  }

  function collectSuiteLinks(csv) {
    return splitCsv(csv).map((name) => ({ suite_name: name }));
  }

  function collectTags(csv) {
    return splitCsv(csv);
  }

  function serializeSteps(container) {
    if (!container) return [];
    const rows = Array.from(container.querySelectorAll("[data-step-row]"));
    return rows
      .map((row, idx) => {
        const action = row.querySelector("[data-step-action]")?.value?.trim() || "";
        const expected =
          row.querySelector("[data-step-expected]")?.value?.trim() || "";
        if (!action && !expected) return null;
        return {
          position: idx + 1,
          action,
          expected,
        };
      })
      .filter(Boolean);
  }

  function reindexSteps(container) {
    if (!container) return;
    Array.from(container.querySelectorAll("[data-step-row]")).forEach((row, idx) => {
      const num = row.querySelector(".w-8");
      if (num) num.textContent = `#${idx + 1}`;
      row.dataset.index = String(idx);
      const ins = row.querySelector(".btn-insert-step");
      const del = row.querySelector(".btn-delete-step");
      if (ins) ins.dataset.insertIndex = String(idx);
      if (del) del.dataset.deleteIndex = String(idx);
    });
  }

  function toggleAddButton(container, addButton) {
    if (!addButton || !container) return;
    const hasSteps = container.querySelectorAll("[data-step-row]").length > 0;
    addButton.classList.toggle("hidden", hasSteps);
  }

  function createStepNode(idx, action = "", expected = "") {
    const div = document.createElement("div");
    div.className = "p-2";
    div.setAttribute("data-step-row", "true");
    div.innerHTML = `
      <div class="flex gap-2 items-start">
        <div class="w-8 text-sm text-gray-600 pt-2 flex-none">#${idx + 1}</div>
        <textarea class="flex-1 border rounded text-sm px-2 py-1" rows="1" placeholder="Action" data-step-action>${action}</textarea>
        <textarea class="flex-1 border rounded text-sm px-2 py-1" rows="1" placeholder="Expected" data-step-expected>${expected}</textarea>
        <button type="button" class="px-3 py-1 text-green-600 border border-green-200 rounded btn-insert-step hover:bg-green-50" data-insert-index="${idx}">+</button>
        <button type="button" class="px-3 py-1 text-red-600 border border-red-200 rounded btn-delete-step hover:bg-red-50" data-delete-index="${idx}">−</button>
      </div>`;
    return div;
  }

  function addStep(container) {
    if (!container) return;
    const idx = container.querySelectorAll("[data-step-row]").length;
    const node = createStepNode(idx);
    container.appendChild(node);
    reindexSteps(container);
  }

  function setupStepsContainer(container, addButton) {
    if (!container) return;
    if (addButton) {
      addButton.addEventListener("click", () => addStep(container));
    }
    // При инициализации покажем кнопку, если шагов нет
    if (addButton) toggleAddButton(container, addButton);

    container.addEventListener("click", (ev) => {
      const insertBtn = ev.target.closest(".btn-insert-step");
      if (insertBtn) {
        const idx = Number(insertBtn.dataset.insertIndex || "0");
        const rows = container.querySelectorAll("[data-step-row]");
        const pos = Math.min(idx + 1, rows.length);
        const node = createStepNode(pos);
        const ref = rows[pos] || null;
        container.insertBefore(node, ref);
        reindexSteps(container);
        if (addButton) toggleAddButton(container, addButton);
        return;
      }

      const deleteBtn = ev.target.closest(".btn-delete-step");
      if (deleteBtn) {
        const idx = Number(deleteBtn.dataset.deleteIndex || "0");
        if (!confirm(`Удалить шаг #${idx + 1}?`)) return;
        const row = container.querySelectorAll("[data-step-row]")[idx];
        if (row) row.remove();
        reindexSteps(container);
        if (addButton) toggleAddButton(container, addButton);
      }
    });
  }

  function setupCreateForm() {
    const form = document.getElementById("create-case-form");
    if (!form) return;

    const stepsContainer = form.querySelector("[data-steps-create]");
    const addBtn = form.querySelector("[data-add-step-create]");
    setupStepsContainer(stepsContainer, addBtn);
    reindexSteps(stepsContainer);
    toggleAddButton(stepsContainer, addBtn);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const actionUrl = "/test_cases";
      const tags = form.querySelector('input[name="tags"]')?.value || "";
      const suites =
        form.querySelector('input[name="suite_links"]')?.value ||
        form.querySelector('input[name="suites"]')?.value ||
        "";

      const payload = {
        name: form.querySelector('input[name="name"]')?.value?.trim(),
        preconditions: form.querySelector('textarea[name="preconditions"]')?.value,
        description: form.querySelector('textarea[name="description"]')?.value,
        expected_result:
          form.querySelector('textarea[name="expected_result"]')?.value,
        tags: collectTags(tags),
        suite_links: collectSuiteLinks(suites),
        steps: serializeSteps(stepsContainer),
      };

      if (!payload.name) {
        alert("Заполните название");
        return;
      }

      try {
      const res = await api.request(actionUrl, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        const id =
          res?.id ||
          res?.body?.id ||
          res?.run_id ||
          res?.test_case_id ||
          res?.items?.[0]?.id;
        if (id) {
          window.location.href = `/testcases?selected_id=${id}`;
        } else {
          window.location.href = "/testcases";
        }
      } catch (err) {
        console.error(err);
        alert(`Не удалось создать тест-кейс: ${err.message}`);
      }
    });
  }

  function setupEditForm() {
    const form = document.getElementById("edit-case-form");
    if (!form) return;
    const tcId = form.dataset.testcaseId;
    const actionUrl = `/test_cases/${tcId}`;
    const stepsContainer = form.querySelector("[data-steps-edit]");
    const addBtn = document.getElementById("btn-add-step-top");

    setupStepsContainer(stepsContainer, addBtn);
    reindexSteps(stepsContainer);
    toggleAddButton(stepsContainer, addBtn);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const tags = form.querySelector('textarea[name="tags"]')?.value || "";
      const suites =
        form.querySelector('textarea[name="suites"]')?.value ||
        form.querySelector('input[name="suite_links"]')?.value ||
        "";

      const payload = {
        name: form.querySelector('input[name="name"]')?.value?.trim(),
        preconditions: form.querySelector('textarea[name="preconditions"]')?.value,
        description: form.querySelector('textarea[name="description"]')?.value,
        expected_result:
          form.querySelector('textarea[name="expected_result"]')?.value,
        tags: collectTags(tags),
        suite_links: collectSuiteLinks(suites),
        steps: serializeSteps(stepsContainer),
      };

      if (!payload.name) {
        alert("Заполните название");
        return;
      }

      try {
        await api.request(actionUrl, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        window.location.href = `/testcases?selected_id=${tcId}`;
      } catch (err) {
        console.error(err);
        alert(`Не удалось сохранить тест-кейс: ${err.message}`);
      }
    });

    const deleteBtn = document.querySelector("[data-delete-case]");
    if (deleteBtn) {
      deleteBtn.addEventListener("click", async () => {
        if (!tcId) return;
        const msg = deleteBtn.dataset.confirm || "Удалить тест-кейс?";
        if (!confirm(msg)) return;
        try {
          await api.request(`/test_cases/${tcId}`, { method: "DELETE" });
          window.location.href = "/testcases";
        } catch (err) {
          console.error(err);
          alert(`Не удалось удалить тест-кейс: ${err.message}`);
        }
      });
    }
  }

  function setupAttachmentActions() {
    document.querySelectorAll("[data-delete-attachment]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const tcId = btn.dataset.testcaseId;
        const attachmentId = btn.dataset.deleteAttachment;
        const msg = btn.dataset.confirm || "Удалить вложение?";
        if (!tcId || !attachmentId) return;
        if (!confirm(msg)) return;
        try {
          await api.request(`/test_cases/${tcId}/attachments/${attachmentId}`, {
            method: "DELETE",
          });
          window.location.reload();
        } catch (err) {
          console.error(err);
          alert(`Не удалось удалить вложение: ${err.message}`);
        }
      });
    });
  }

  function setupTagDropdown() {
    const root = document.getElementById("tags-filter-root");
    const pageRoot = document.getElementById("testcases-root");
    if (!root || !pageRoot) return;

    const toggle = document.getElementById("tags-toggle");
    const dropdown = document.getElementById("tags-dropdown");
    const listEl = document.getElementById("tags-list");
    const searchInput = document.getElementById("tags-search");
    const applyBtn = document.getElementById("tags-apply");
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
    const initialSelectedArr = splitCsv(initialCsv);
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

    listEl.addEventListener("change", function (e) {
      const cb = e.target.closest(".tag-checkbox");
      if (!cb) return;
      const name = cb.dataset.name;
      if (cb.checked) selected.add(name);
      else selected.delete(name);
      updateSummary();
    });

    searchInput.addEventListener("input", function () {
      renderList(this.value || "");
    });

    applyBtn.addEventListener("click", function () {
      const arr = Array.from(selected);
      hidden.value = arr.join(",");
      const params = new URLSearchParams(window.location.search);
      if (arr.length) params.set("tags", arr.join(","));
      else params.delete("tags");
      // сбрасываем курсор пагинации при смене фильтра
      params.delete("cursor");
      window.location.search = params.toString();
    });

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

  document.addEventListener("DOMContentLoaded", () => {
    setupTagDropdown();
    setupCreateForm();
    setupEditForm();
    setupAttachmentActions();
  });
})();


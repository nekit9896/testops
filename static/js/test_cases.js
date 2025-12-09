(() => {
  // ========== Парсинг ошибки ==========
  function parseErrorMessage(message) {
    if (!message) return "Неизвестная ошибка";
    
    // Попробовать парсить как JSON целиком
    try {
      const parsed = JSON.parse(message);
      return parsed.description || parsed.message || parsed.name || message;
    } catch (e) {
      // Не JSON целиком
    }
    
    // Попробовать найти JSON внутри строки (например "Текст: {json}")
    const jsonMatch = message.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      try {
        const parsed = JSON.parse(jsonMatch[0]);
        return parsed.description || parsed.message || parsed.name || message;
      } catch (e) {
        // не валидный JSON внутри
      }
    }
    
    return message;
  }

  // ========== Toast уведомления ==========
  const toast = {
    container: null,
    init() {
      if (this.container) return;
      this.container = document.createElement("div");
      this.container.id = "toast-container";
      this.container.className = "fixed top-4 right-4 z-50 flex flex-col gap-2";
      document.body.appendChild(this.container);
    },
    show(message, type = "error", duration = 10000) {
      this.init();
      const toastEl = document.createElement("div");
      const bgColor = type === "error" ? "bg-red-500" : type === "success" ? "bg-green-500" : "bg-blue-500";
      toastEl.className = `${bgColor} text-white px-4 py-3 rounded shadow-lg max-w-md animate-fade-in flex items-start gap-2`;
      
      const displayMsg = parseErrorMessage(message);
      
      toastEl.innerHTML = `
        <span class="flex-1">${displayMsg}</span>
        <button class="ml-2 font-bold hover:opacity-75" onclick="this.parentElement.remove()">×</button>
      `;
      this.container.appendChild(toastEl);
      
      if (duration > 0) {
        setTimeout(() => toastEl.remove(), duration);
      }
    },
    error(message) { this.show(message, "error"); },
    success(message) { this.show(message, "success"); },
    info(message) { this.show(message, "info"); }
  };

  // ========== Автоматическое изменение размера textarea ==========
  function autoResizeTextarea(textarea, maxRows = 15, minRows = 1) {
    if (!textarea) return;
    
    const lineHeight = parseInt(getComputedStyle(textarea).lineHeight) || 20;
    const paddingTop = parseInt(getComputedStyle(textarea).paddingTop) || 0;
    const paddingBottom = parseInt(getComputedStyle(textarea).paddingBottom) || 0;
    const minHeight = lineHeight * minRows + paddingTop + paddingBottom;
    const maxHeight = lineHeight * maxRows + paddingTop + paddingBottom;
    
    // Функция изменения размера
    const resize = () => {
      textarea.style.height = "auto";
      const scrollHeight = textarea.scrollHeight;
      textarea.style.height = Math.min(Math.max(scrollHeight, minHeight), maxHeight) + "px";
      textarea.style.overflowY = scrollHeight > maxHeight ? "auto" : "hidden";
    };
    
    // Применить сразу и при вводе
    resize();
    textarea.addEventListener("input", resize);
  }

  function setupAutoResizeForForm(form) {
    if (!form) return;
    
    // Большие поля: preconditions, description, expected_result — макс 15 строк, мин 2 строки
    ["preconditions", "description", "expected_result"].forEach(name => {
      const textarea = form.querySelector(`textarea[name="${name}"]`);
      if (textarea) autoResizeTextarea(textarea, 15, 2);
    });
    
    // Поля шагов: action, expected — макс 5 строк, мин 2 строка
    form.querySelectorAll("[data-step-action], [data-step-expected]").forEach(textarea => {
      autoResizeTextarea(textarea, 5, 1.5);
    });
  }

  // ========== Валидация полей ==========
  function validateField(input, errorMessage) {
    const value = input?.value?.trim() || "";
    if (!value) {
      input.classList.add("border-red-500", "bg-red-50");
      toast.error(errorMessage);
      input.focus();
      return false;
    }
    input.classList.remove("border-red-500", "bg-red-50");
    return true;
  }

  function clearFieldError(input) {
    if (input) {
      input.classList.remove("border-red-500", "bg-red-50");
    }
  }

  // ========== API ==========
  const api = {
    async request(url, { method = "GET", body, headers = {} } = {}) {
      const opts = {
        method,
        credentials: "same-origin",
        headers: {
          // Явно указываем Accept: application/json чтобы бэкенд
          // не делал redirect и возвращал JSON-ответ
          Accept: "application/json",
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
    // Убираем лишний padding, используем только py-1 для небольшого вертикального отступа
    div.className = "py-1";
    div.setAttribute("data-step-row", "true");
    div.innerHTML = `
      <div class="flex gap-2 items-center">
        <div class="w-8 text-sm text-gray-600 flex-none">#${idx + 1}</div>
        <textarea class="flex-1 border rounded text-sm px-2 py-1" rows="1" placeholder="Action" data-step-action>${action}</textarea>
        <textarea class="flex-1 border rounded text-sm px-2 py-1" rows="1" placeholder="Expected" data-step-expected>${expected}</textarea>
        <button type="button" class="px-3 py-1 text-green-600 border border-green-200 rounded btn-insert-step hover:bg-green-50 font-bold" data-insert-index="${idx}">+</button>
        <button type="button" class="px-3 py-1 text-red-600 border border-red-200 rounded btn-delete-step hover:bg-red-50 font-bold" data-delete-index="${idx}">−</button>
      </div>`;
    
    // Применяем автоматическое изменение размера к новым textarea (макс 5 строк, мин 1 строка)
    div.querySelectorAll("[data-step-action], [data-step-expected]").forEach(textarea => {
      autoResizeTextarea(textarea, 5, 1.5);
    });
    
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

    // Автоматическое изменение размера textarea
    setupAutoResizeForForm(form);

    // Очистка ошибки при вводе в поле названия
    const nameInput = form.querySelector('input[name="name"]');
    if (nameInput) {
      nameInput.addEventListener("input", () => clearFieldError(nameInput));
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const actionUrl = "/test_cases";
      const nameInput = form.querySelector('input[name="name"]');
      const tags = form.querySelector('input[name="tags"]')?.value || "";
      const suites =
        form.querySelector('input[name="suite_links"]')?.value ||
        form.querySelector('input[name="suites"]')?.value ||
        "";

      // Валидация названия
      if (!validateField(nameInput, "Название тест-кейса обязательно")) {
        return;
      }

      const payload = {
        name: nameInput.value.trim(),
        preconditions: form.querySelector('textarea[name="preconditions"]')?.value,
        description: form.querySelector('textarea[name="description"]')?.value,
        expected_result:
          form.querySelector('textarea[name="expected_result"]')?.value,
        tags: collectTags(tags),
        suite_links: collectSuiteLinks(suites),
        steps: serializeSteps(stepsContainer),
      };

      try {
        const res = await api.request(actionUrl, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast.success("Тест-кейс успешно создан");
        const id =
          res?.id ||
          res?.body?.id ||
          res?.run_id ||
          res?.test_case_id ||
          res?.items?.[0]?.id;
        setTimeout(() => {
          if (id) {
            window.location.href = `/testcases?selected_id=${id}`;
          } else {
            window.location.href = "/testcases";
          }
        }, 500);
      } catch (err) {
        console.error(err);
        toast.error(`Не удалось создать тест-кейс: ${err.message}`);
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

    // Автоматическое изменение размера textarea
    setupAutoResizeForForm(form);

    // Очистка ошибки при вводе в поле названия
    const nameInput = form.querySelector('input[name="name"]');
    if (nameInput) {
      nameInput.addEventListener("input", () => clearFieldError(nameInput));
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const nameInput = form.querySelector('input[name="name"]');
      const tags = form.querySelector('textarea[name="tags"]')?.value || "";
      const suites =
        form.querySelector('textarea[name="suites"]')?.value ||
        form.querySelector('input[name="suite_links"]')?.value ||
        "";

      // Валидация названия
      if (!validateField(nameInput, "Название тест-кейса обязательно")) {
        return;
      }

      const payload = {
        name: nameInput.value.trim(),
        preconditions: form.querySelector('textarea[name="preconditions"]')?.value,
        description: form.querySelector('textarea[name="description"]')?.value,
        expected_result:
          form.querySelector('textarea[name="expected_result"]')?.value,
        tags: collectTags(tags),
        suite_links: collectSuiteLinks(suites),
        steps: serializeSteps(stepsContainer),
      };

      try {
        await api.request(actionUrl, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        toast.success("Тест-кейс успешно сохранён");
        setTimeout(() => {
          window.location.href = `/testcases?selected_id=${tcId}`;
        }, 500);
      } catch (err) {
        console.error(err);
        toast.error(`Не удалось сохранить тест-кейс: ${err.message}`);
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
          toast.success("Тест-кейс удалён");
          setTimeout(() => {
            window.location.href = "/testcases";
          }, 500);
        } catch (err) {
          console.error(err);
          toast.error(`Не удалось удалить тест-кейс: ${err.message}`);
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
          toast.success("Вложение удалено");
          setTimeout(() => window.location.reload(), 500);
        } catch (err) {
          console.error(err);
          toast.error(`Не удалось удалить вложение: ${err.message}`);
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

      const targetUrl =
        window.location.pathname + "?" + params.toString();

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
          // if prev link was absent, append near pagination container
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

  document.addEventListener("DOMContentLoaded", () => {
    setupTagDropdown();
    setupCreateForm();
    setupEditForm();
    setupAttachmentActions();

    // Автоприменение для include_deleted и sort
    document
      .querySelectorAll("[data-auto-submit-filter]")
      .forEach((el) => {
        el.addEventListener("change", () => {
          const form = el.closest("form");
          if (form) {
            form.submit();
          }
        });
      });
  });
})();


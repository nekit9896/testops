/**
 * ReportsPage инкапсулирует всю логику курсовой пагинации:
 *  - хранит курсоры "новые"/"старые"
 *  - рисует строки таблицы
 *  - управляет кнопками и сообщениями об ошибках
 */
class ReportsPage {
  constructor({ dataUrl, limit }) {
    // REST endpoint и лимит записей берутся из data-атрибутов шаблона
    this.dataUrl = dataUrl;
    this.limit = limit;
    this.state = {
      nextCursor: null,
      prevCursor: null,
    };

    this.filterConfig = {
      stand: { param: "stand", responseKey: "stands" },
      status: { param: "status", responseKey: "statuses" },
    };
    this.filters = {
      stand: [],
      status: [],
    };
    this.availableFilters = {
      stand: [],
      status: [],
    };

    // Фильтры по дате
    this.dateFilters = {
      from: null,
      to: null,
    };

    this.tableBody = document.getElementById("reports-body");
    this.message = document.getElementById("reports-message");
    this.loadingIndicator = document.getElementById("reports-loading");
    this.prevButton = document.getElementById("reports-prev");
    this.nextButton = document.getElementById("reports-next");
    this.tableWrapper = document.querySelector("[data-reports-table-wrapper]");
    this.defaultTableHeight = null;

    // Элементы фильтра по дате
    this.dateFromInput = document.getElementById("date-from");
    this.dateToInput = document.getElementById("date-to");
    this.dateApplyButton = document.getElementById("date-filter-apply");
    this.dateResetButton = document.getElementById("date-filter-reset");
    this.dateError = document.getElementById("date-error");
    this.dateTrigger = document.getElementById("date-filter-trigger");
    this.datePanel = document.getElementById("date-filter-panel");

    this.filterControls = this.initFilterControls();
    this.handleDocumentClick = this.handleDocumentClick.bind(this);

    this.bindEvents();
    this.loadPage();
  }

  initFilterControls() {
    const controls = {};

    Array.from(document.querySelectorAll("[data-filter-key]")).forEach((node) => {
      const key = node.dataset.filterKey;
      if (!key) {
        return;
      }

      controls[key] = {
        container: node,
        toggle: node.querySelector("[data-filter-trigger]"),
        panel: node.querySelector("[data-filter-panel]"),
        options: node.querySelector("[data-filter-options]"),
        apply: node.querySelector("[data-filter-apply]"),
        counter: node.querySelector("[data-filter-counter]"),
        reset: node.querySelector("[data-filter-reset]"),
      };

      if (controls[key].panel) {
        controls[key].panel.addEventListener("click", (event) => {
          event.stopPropagation();
        });
      }
    });

    return controls;
  }

  bindEvents() {
    // "▲" — листаем к более новым записям
    if (this.prevButton) {
      this.prevButton.addEventListener("click", () => {
        if (this.state.prevCursor) {
          this.loadPage({ cursor: this.state.prevCursor, direction: "prev" });
        }
      });
    }

    // "▼" — листаем к более старым записям
    if (this.nextButton) {
      this.nextButton.addEventListener("click", () => {
        if (this.state.nextCursor) {
          this.loadPage({ cursor: this.state.nextCursor, direction: "next" });
        }
      });
    }

    Object.keys(this.filterControls).forEach((key) => {
      const control = this.filterControls[key];
      if (!control) {
        return;
      }

      if (control.toggle) {
        control.toggle.addEventListener("click", (event) => {
          event.stopPropagation();
          this.toggleFilterPanel(key);
        });
      }

      if (control.apply) {
        control.apply.addEventListener("click", () => {
          this.handleFilterApply(key);
        });
      }

      if (control.reset) {
        control.reset.addEventListener("click", () => {
          this.handleFilterReset(key);
        });
      }
    });

    document.addEventListener("click", this.handleDocumentClick);

    // Обработчики для фильтров по дате
    if (this.dateTrigger && this.datePanel) {
      this.dateTrigger.addEventListener("click", (event) => {
        event.stopPropagation();
        this.toggleDatePanel();
      });
      // Авто-подстановка сегодняшней даты в "С" при первом открытии
      this.dateTrigger.addEventListener("click", () => {
        if (this.dateFromInput && !this.dateFromInput.value) {
          const today = new Date();
          const yyyy = today.getFullYear();
          const mm = String(today.getMonth() + 1).padStart(2, "0");
          const dd = String(today.getDate()).padStart(2, "0");
          this.dateFromInput.value = `${yyyy}-${mm}-${dd}`;
        }
      });
    }

    if (this.dateApplyButton) {
      this.dateApplyButton.addEventListener("click", () => {
        this.handleDateFilterApply();
      });
    }

    if (this.dateResetButton) {
      this.dateResetButton.addEventListener("click", () => {
        this.handleDateFilterReset();
      });
    }

    // При нажатии Enter в полях даты — применить фильтр
    if (this.dateFromInput) {
      this.dateFromInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
          this.handleDateFilterApply();
        }
      });
    }
    if (this.dateToInput) {
      this.dateToInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
          this.handleDateFilterApply();
        }
      });
    }
  }

  /**
   * Валидирует и применяет фильтр по дате.
   */
  handleDateFilterApply() {
    const fromValue = this.dateFromInput ? this.dateFromInput.value : null;
    const toValue = this.dateToInput ? this.dateToInput.value : null;

    // Скрываем предыдущую ошибку
    this.showDateError("");

    // Валидация: дата "с" должна быть <= дате "до"
    if (fromValue && toValue && fromValue > toValue) {
      this.showDateError("Дата 'С' должна быть меньше или равна дате 'По'");
      return;
    }

    this.dateFilters.from = fromValue || null;
    this.dateFilters.to = toValue || null;
    this.loadPage();
  }

  /**
   * Сбрасывает фильтр по дате.
   */
  handleDateFilterReset() {
    if (this.dateFromInput) {
      this.dateFromInput.value = "";
    }
    if (this.dateToInput) {
      this.dateToInput.value = "";
    }
    this.showDateError("");

    const hadDateFilter = this.dateFilters.from || this.dateFilters.to;
    this.dateFilters.from = null;
    this.dateFilters.to = null;

    if (hadDateFilter) {
      this.loadPage();
    }
  }

  /**
   * Показывает/скрывает сообщение об ошибке даты.
   */
  showDateError(text) {
    if (!this.dateError) {
      return;
    }
    if (!text) {
      this.dateError.classList.add("hidden");
      this.dateError.textContent = "";
      return;
    }
    this.dateError.textContent = text;
    this.dateError.classList.remove("hidden");
  }

  handleDocumentClick(event) {
    // Закрыть панель дат, если клик вне
    if (this.datePanel && this.dateTrigger) {
      if (!this.datePanel.contains(event.target) && !this.dateTrigger.contains(event.target)) {
        this.closeDatePanel();
      }
    }

    Object.keys(this.filterControls).forEach((key) => {
      const control = this.filterControls[key];
      if (!control || !control.container) {
        return;
      }

      if (!control.container.contains(event.target)) {
        this.closeFilterPanel(key);
      }
    });
  }

  toggleDatePanel() {
    if (!this.datePanel) return;
    const isOpen = !this.datePanel.classList.contains("hidden");
    if (isOpen) {
      this.closeDatePanel();
    } else {
      // закрываем остальные фильтры
      Object.keys(this.filterControls).forEach((key) => this.closeFilterPanel(key));
      this.datePanel.classList.remove("hidden");
    }
  }

  closeDatePanel() {
    if (this.datePanel) {
      this.datePanel.classList.add("hidden");
    }
  }

  toggleFilterPanel(key) {
    const control = this.filterControls[key];
    if (!control || !control.panel) {
      return;
    }

    const isOpen = !control.panel.classList.contains("hidden");
    Object.keys(this.filterControls).forEach((filterKey) => {
      if (filterKey !== key) {
        this.closeFilterPanel(filterKey);
      }
    });

    if (isOpen) {
      this.closeFilterPanel(key);
    } else {
      control.panel.classList.remove("hidden");
    }
  }

  closeFilterPanel(key) {
    const control = this.filterControls[key];
    if (control && control.panel) {
      control.panel.classList.add("hidden");
    }
  }

  handleFilterApply(key) {
    const control = this.filterControls[key];
    if (!control || !control.options) {
      return;
    }

    const selectedValues = Array.from(
      control.options.querySelectorAll('input[type="checkbox"]')
    )
      .filter((input) => input.checked)
      .map((input) => input.value);

    this.filters[key] = selectedValues;
    this.updateFilterCounters();
    this.closeFilterPanel(key);
    this.loadPage();
  }

  handleFilterReset(key) {
    const control = this.filterControls[key];
    if (!control || !control.options) {
      return;
    }

    control.options
      .querySelectorAll('input[type="checkbox"]')
      .forEach((input) => {
        input.checked = false;
      });

    const hadSelection = (this.filters[key] || []).length > 0;
    this.filters[key] = [];
    this.updateFilterCounters();
    this.closeFilterPanel(key);

    if (hadSelection) {
      this.loadPage();
    }
  }

  /**
   * Показывает/скрывает индикатор загрузки и блокирует кнопки на время запроса.
   */
  setLoading(isLoading) {
    if (this.loadingIndicator) {
      this.loadingIndicator.classList.toggle("hidden", !isLoading);
    }
    [this.prevButton, this.nextButton].forEach((button) => {
      if (button) {
        button.disabled = isLoading || button.dataset.disabled === "true";
      }
    });
  }

  /**
   * Загружает очередную страницу отчётов.
   * cursor=null означает стартовую страницу (последние записи).
   */
  buildQueryParams({ cursor, direction }) {
    const params = new URLSearchParams({ limit: this.limit, direction });
    if (cursor) {
      params.append("cursor", cursor);
    }

    Object.keys(this.filterConfig).forEach((key) => {
      const paramName = this.filterConfig[key].param;
      const selected = this.filters[key] || [];
      selected.forEach((value) => {
        params.append(paramName, value);
      });
    });

    // Добавляем параметры фильтрации по дате
    if (this.dateFilters.from) {
      params.append("start_date_from", this.dateFilters.from);
    }
    if (this.dateFilters.to) {
      params.append("start_date_to", this.dateFilters.to);
    }

    return params;
  }

  async loadPage({ cursor = null, direction = "next" } = {}) {
    this.setLoading(true);
    const params = this.buildQueryParams({ cursor, direction });

    try {
      const response = await fetch(`${this.dataUrl}?${params.toString()}`);
      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`);
      }
      const data = await response.json();
      this.renderRows(data.items);
      this.updateState(data);
      this.updateAvailableFilters(data.filters);
    } catch (error) {
      this.showMessage("Не удалось загрузить отчёты. Попробуйте позже.", true);
      console.error(error);
    } finally {
      this.setLoading(false);
    }
  }

  /**
   * Сохраняет курсоры и актуализирует активность кнопок списка.
   */
  updateState({ next_cursor, prev_cursor, has_next, has_prev }) {
    this.state.nextCursor = next_cursor;
    this.state.prevCursor = prev_cursor;

    if (this.nextButton) {
      this.nextButton.disabled = !has_next;
      this.nextButton.dataset.disabled = (!has_next).toString();
    }
    if (this.prevButton) {
      this.prevButton.disabled = !has_prev;
      this.prevButton.dataset.disabled = (!has_prev).toString();
    }
  }

  /**
   * Перерисовывает тело таблицы.
   * При пустом списке показываем дружелюбное сообщение.
   */
  updateAvailableFilters(filtersPayload) {
    const payload =
      filtersPayload && typeof filtersPayload === "object" ? filtersPayload : {};

    Object.keys(this.filterConfig).forEach((key) => {
      const responseKey = this.filterConfig[key].responseKey;
      const valuesRaw = payload[responseKey];
      this.availableFilters[key] = Array.isArray(valuesRaw) ? valuesRaw : [];
    });

    this.renderFilterOptions();
  }

  renderFilterOptions() {
    Object.keys(this.filterControls).forEach((key) => {
      const control = this.filterControls[key];
      if (!control || !control.options) {
        return;
      }

      const values = this.availableFilters[key] || [];
      if (!values.length) {
        control.options.innerHTML =
          '<p class="text-xs text-gray-400">Нет доступных значений</p>';
        return;
      }

      control.options.innerHTML = values
        .map((value, index) => {
          const safeValue = this.escapeHtml(value);
          const inputId = this.buildFilterInputId(key, value, index);
          const selected = this.filters[key] || [];
          const isChecked = selected.includes(value);
          return `
            <label class="flex items-center gap-2 text-xs text-gray-700" for="${inputId}">
              <input id="${inputId}"
                    type="checkbox"
                    value="${safeValue}"
                    class="h-3 w-3 rounded border-indigo-600 text-indigo-600 accent-indigo-600 focus:ring-indigo-500"
                    ${isChecked ? "checked" : ""}>
              <span class="truncate" title="${safeValue}">${safeValue}</span>
            </label>`;
        })
        .join("");
    });

    this.updateFilterCounters();
  }

  buildFilterInputId(key, value, index) {
    const normalized = String(value)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "");
    return `filter-${key}-${normalized || index}`;
  }

  updateFilterCounters() {
    Object.keys(this.filterControls).forEach((key) => {
      const control = this.filterControls[key];
      if (!control || !control.counter) {
        return;
      }

      const count = (this.filters[key] || []).length;
      control.counter.textContent = count ? String(count) : "";
      control.counter.classList.toggle("hidden", count === 0);
    });
  }

  renderRows(items = []) {
    if (!this.tableBody) {
      return;
    }

    if (!items.length) {
      const emptyText = this.hasActiveFilters()
        ? "Ничего не найдено по выбранным фильтрам."
        : "Отчётов пока нет.";

      this.tableBody.innerHTML = `
        <tr>
          <td colspan="7" class="px-4 py-6 text-center text-sm text-gray-500">
            ${emptyText}
          </td>
        </tr>`;
      this.showMessage(emptyText, false);
      this.adjustTableHeight();
      return;
    }

    this.showMessage("", false);
    const rows = items
      .map((item) => {
        const statusValue = (item.status || "").toLowerCase();
        const statusClass =
          statusValue === "fail"
            ? "text-red-600"
            : statusValue === "passed"
            ? "text-green-600"
            : "text-gray-800";

        const runName = this.escapeHtml(item.run_name || "-");
        const startDate = this.escapeHtml(this.formatLocalDate(item.start_date));
        const endDate = this.escapeHtml(this.formatLocalDate(item.end_date));
        const stand = this.escapeHtml(item.stand || "-");
        const status = this.escapeHtml(item.status || "-");

        return `
          <tr class="hover:bg-gray-50">
            <td class="px-4 py-2 text-sm text-gray-900">${item.id}</td>
            <td class="px-4 py-2 text-sm text-gray-900">${runName}</td>
            <td class="px-4 py-2 text-sm text-gray-600">${startDate}</td>
            <td class="px-4 py-2 text-sm text-gray-600">${endDate}</td>
            <td class="px-4 py-2 text-sm text-gray-600">${stand}</td>
            <td class="px-4 py-2 text-sm font-semibold ${statusClass}">
              ${status}
            </td>
            <td class="px-4 py-2 text-sm">
              <a href="/reports/${item.id}" class="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer">
                Открыть
              </a>
            </td>
          </tr>`;
      })
      .join("");

    this.tableBody.innerHTML = rows;
    this.adjustTableHeight();
  }

  hasActiveFilters() {
    const hasStandardFilters = Object.keys(this.filters).some(
      (key) => (this.filters[key] || []).length > 0
    );
    const hasDateFilters = this.dateFilters.from || this.dateFilters.to;
    return hasStandardFilters || hasDateFilters;
  }

  /**
   * Управляет строкой сообщения под заголовком (ошибки, пустой список и т.п.).
   */
  showMessage(text, isError) {
    if (!this.message) {
      return;
    }
    if (!text) {
      this.message.classList.add("hidden");
      this.message.textContent = "";
      return;
    }
    this.message.textContent = text;
    this.message.classList.remove("hidden");
    this.message.classList.toggle("text-red-600", Boolean(isError));
    this.message.classList.toggle("text-gray-500", !isError);
  }

  escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /**
   * Форматирует ISO дату в локальный часовой пояс пользователя.
   * @param {string} isoDateString - дата в формате ISO (например "2025-12-11T12:30:00")
   * @returns {string} отформатированная дата или "-" если входные данные пустые
   */
  formatLocalDate(isoDateString) {
    if (!isoDateString || isoDateString === "-") {
      return "-";
    }
    try {
      const date = new Date(isoDateString);
      if (isNaN(date.getTime())) {
        return isoDateString;
      }
      const pad = (n) => String(n).padStart(2, "0");
      const hh = pad(date.getHours());
      const mm = pad(date.getMinutes());
      const ss = pad(date.getSeconds());
      const dd = pad(date.getDate());
      const mon = pad(date.getMonth() + 1);
      const yyyy = date.getFullYear();
      return `${hh}:${mm}:${ss}, ${dd}.${mon}.${yyyy}`;
    } catch {
      return isoDateString;
    }
  }

  adjustTableHeight() {
    if (!this.tableWrapper) {
      return;
    }

    const header = this.tableWrapper.querySelector("thead");
    const headerHeight = header
      ? header.getBoundingClientRect().height
      : 0;
    const sampleRow = this.tableBody
      ? this.tableBody.querySelector("tr")
      : null;
    const rowHeight = sampleRow
      ? sampleRow.getBoundingClientRect().height
      : 48;

    if (!this.defaultTableHeight) {
      const fallbackLimit = Number(this.limit) || 0;
      this.defaultTableHeight = headerHeight + rowHeight * fallbackLimit;
    }

    const bodyHeight = this.tableBody
      ? this.tableBody.getBoundingClientRect().height
      : 0;
    const desiredHeight = headerHeight + bodyHeight;
    const targetHeight = Math.max(
      this.defaultTableHeight || 0,
      desiredHeight
    );

    this.tableWrapper.style.minHeight = `${Math.ceil(targetHeight)}px`;
  }
}
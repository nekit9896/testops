class ReportsPage {
  constructor({ dataUrl, limit }) {
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

    this.tableBody = document.getElementById("reports-body");
    this.message = document.getElementById("reports-message");
    this.loadingIndicator = document.getElementById("reports-loading");
    this.prevButton = document.getElementById("reports-prev");
    this.nextButton = document.getElementById("reports-next");
    this.tableWrapper = document.querySelector("[data-reports-table-wrapper]");
    this.defaultTableHeight = null;

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
    if (this.prevButton) {
      this.prevButton.addEventListener("click", () => {
        if (this.state.prevCursor) {
          this.loadPage({ cursor: this.state.prevCursor, direction: "prev" });
        }
      });
    }

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
  }

  handleDocumentClick(event) {
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
            <label class="flex items-center gap-2 text-sm text-gray-700" for="${inputId}">
              <input id="${inputId}"
                     type="checkbox"
                     value="${safeValue}"
                     class="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
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
        const startDate = this.escapeHtml(item.start_date || "-");
        const endDate = this.escapeHtml(item.end_date || "-");
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
    return Object.keys(this.filters).some(
      (key) => (this.filters[key] || []).length > 0
    );
  }

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


class ReportsPage {
  constructor({ dataUrl, limit }) {
    this.dataUrl = dataUrl;
    this.limit = limit;
    this.state = {
      nextCursor: null,
      prevCursor: null,
    };

    this.tableBody = document.getElementById("reports-body");
    this.message = document.getElementById("reports-message");
    this.loadingIndicator = document.getElementById("reports-loading");
    this.prevButton = document.getElementById("reports-prev");
    this.nextButton = document.getElementById("reports-next");

    this.bindEvents();
    this.loadPage();
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

  async loadPage({ cursor = null, direction = "next" } = {}) {
    this.setLoading(true);
    const params = new URLSearchParams({ limit: this.limit, direction });
    if (cursor) {
      params.append("cursor", cursor);
    }

    try {
      const response = await fetch(`${this.dataUrl}?${params.toString()}`);
      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`);
      }
      const data = await response.json();
      this.renderRows(data.items);
      this.updateState(data);
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

  renderRows(items = []) {
    if (!this.tableBody) {
      return;
    }

    if (!items.length) {
      this.tableBody.innerHTML = `
        <tr>
          <td colspan="7" class="px-4 py-6 text-center text-sm text-gray-500">
            Отчётов пока нет.
          </td>
        </tr>`;
      this.showMessage("Отчётов пока нет.", false);
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
        return `
          <tr class="hover:bg-gray-50">
            <td class="px-4 py-2 text-sm text-gray-900">${item.id}</td>
            <td class="px-4 py-2 text-sm text-gray-900">${item.run_name || "-"}</td>
            <td class="px-4 py-2 text-sm text-gray-600">${item.start_date || "-"}</td>
            <td class="px-4 py-2 text-sm text-gray-600">${item.end_date || "-"}</td>
            <td class="px-4 py-2 text-sm text-gray-600">${item.stand || "-"}</td>
            <td class="px-4 py-2 text-sm font-semibold ${statusClass}">
              ${item.status || "-"}
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
    this.message.classList.toggle("text-red-600", !!isError);
    this.message.classList.toggle("text-gray-500", !isError);
  }
}


/**
 * Модуль для работы с шагами тест-кейса.
 * Зависимости: namespace.js, common/utils.js
 */
(function() {
  'use strict';

  const { autoResizeTextarea } = window.TestOps.utils;

  function serializeSteps(container) {
    if (!container) return [];
    const rows = Array.from(container.querySelectorAll("[data-step-row]"));
    return rows
      .map((row, idx) => {
        const action = row.querySelector("[data-step-action]")?.value?.trim() || "";
        const expected = row.querySelector("[data-step-expected]")?.value?.trim() || "";
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
    
    // Применяем автоматическое изменение размера к новым textarea
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

  // Экспорт
  window.TestOps.steps = {
    serializeSteps,
    reindexSteps,
    toggleAddButton,
    createStepNode,
    addStep,
    setupStepsContainer,
  };
})();


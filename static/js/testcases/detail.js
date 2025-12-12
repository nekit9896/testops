/**
 * Загрузка содержания тест-кейса через Partial Rendering.
 * Зависимости: namespace.js, common/toast.js, common/utils.js, testcases/forms.js, testcases/attachments.js
 */
(function() {
  'use strict';

  const { toast, utils, forms, attachments } = window.TestOps;

  // Индикатор загрузки
  function showLoading(container) {
    container.innerHTML = `
      <div class="flex items-center justify-center h-32">
        <svg class="w-8 h-8 animate-spin text-blue-500" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="ml-2 text-gray-500">Загрузка...</span>
      </div>
    `;
  }

  // Управляет загрузкой/переключением содержания тест-кейса через partial HTML
  function setupTestcaseDetailLoader() {
    const tbody = document.getElementById("cases-tbody");
    const detailPanel = document.getElementById("testcase-detail-panel");
    const createBtn = document.getElementById("btn-create-testcase");
    
    if (!detailPanel) return;
    
    // Обработчик для кнопки "Создать тест-кейс"
    if (createBtn) {
      createBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        
        // URL для partial (только HTML панели)
        const partialUrl = utils.buildPartialUrl(null, true);
        // URL для адресной строки (полный с фильтрами)
        const browserUrl = utils.buildUrlWithFilters({ create: "1", selected_id: null });
        
        showLoading(detailPanel);
        
        // Снимаем выделение со всех строк
        if (tbody) {
          tbody.querySelectorAll(".testcase-row").forEach(row => {
            row.classList.remove("bg-blue-50");
          });
        }
        
        try {
          const res = await fetch(partialUrl, { credentials: "same-origin" });
          if (!res.ok) throw new Error(`Request failed: ${res.status}`);
          
          // Partial возвращает только HTML панели — вставляем напрямую
          detailPanel.innerHTML = await res.text();
          forms.setupCreateForm();
          
          window.history.pushState({}, "", browserUrl);
          
        } catch (err) {
          console.error("Не удалось открыть форму создания:", err);
          toast.error("Не удалось открыть форму создания");
          detailPanel.innerHTML = `<div class="text-red-500 p-4">Ошибка загрузки формы</div>`;
        }
      });
    }
    
    if (!tbody) return;
    
    // Используем делегирование событий для поддержки динамически добавленных строк
    tbody.addEventListener("click", async (e) => {
      const link = e.target.closest(".testcase-link");
      if (!link) return;
      
      e.preventDefault();
      
      const testcaseId = link.dataset.testcaseId;
      if (!testcaseId) return;
      
      // URL для partial (только HTML панели)
      const partialUrl = utils.buildPartialUrl(testcaseId);
      // URL для адресной строки (полный с фильтрами)
      const browserUrl = utils.buildUrlWithFilters({ selected_id: testcaseId });
      
      showLoading(detailPanel);
      
      // Снимаем выделение со всех строк и выделяем текущую
      tbody.querySelectorAll(".testcase-row").forEach(row => {
        row.classList.remove("bg-blue-50");
      });
      const currentRow = tbody.querySelector(`.testcase-row[data-testcase-id="${testcaseId}"]`);
      if (currentRow) {
        currentRow.classList.add("bg-blue-50");
      }
      
      try {
        const res = await fetch(partialUrl, { credentials: "same-origin" });
        if (!res.ok) {
          throw new Error(`Request failed: ${res.status}`);
        }
        
        // Partial возвращает только HTML панели — вставляем напрямую
        detailPanel.innerHTML = await res.text();
        
        // Переинициализируем обработчики для новой формы
        forms.setupEditForm();
        attachments.setupAttachmentActions();
        attachments.setupFileUpload();
        
        // Обновляем URL в адресной строке
        window.history.pushState({}, "", browserUrl);
        
      } catch (err) {
        console.error("Не удалось загрузить тест-кейс:", err);
        toast.error("Не удалось загрузить тест-кейс");
        detailPanel.innerHTML = `
          <div class="text-red-500 p-4">
            Ошибка загрузки тест-кейса. <a href="${browserUrl}" class="underline">Попробовать ещё раз</a>
          </div>
        `;
      }
    });
    
    // Обработка навигации браузера (кнопки назад/вперёд)
    window.addEventListener("popstate", () => {
      window.location.reload();
    });
  }

  // Экспорт
  window.TestOps.detail = {
    setupTestcaseDetailLoader,
  };
})();


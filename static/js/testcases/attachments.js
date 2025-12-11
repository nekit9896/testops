/**
 * Работа с вложениями тест-кейсов.
 * Зависимости: namespace.js, common/toast.js, common/api.js
 */
(function() {
  'use strict';

  const { toast, api } = window.TestOps;

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

  function setupFileUpload() {
    const attachBtn = document.getElementById("btn-attach-file");
    const fileInput = document.getElementById("hidden-file-input");
    
    if (!attachBtn || !fileInput) return;
    
    const uploadUrl = attachBtn.dataset.uploadUrl;
    if (!uploadUrl) return;
    
    // Клик по кнопке открывает диалог выбора файла
    attachBtn.addEventListener("click", () => {
      fileInput.click();
    });
    
    // При выборе файла — автоматически загружаем
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files[0];
      if (!file) return;
      
      // Показываем индикатор загрузки
      const originalText = attachBtn.innerHTML;
      attachBtn.innerHTML = `
        <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        Загрузка...
      `;
      attachBtn.disabled = true;
      
      try {
        const formData = new FormData();
        formData.append("file", file);
        
        const res = await fetch(uploadUrl, {
          method: "POST",
          credentials: "same-origin",
          body: formData,
        });
        
        if (!res.ok) {
          const text = await res.text().catch(() => "");
          throw new Error(text || `Request failed (${res.status})`);
        }
        
        toast.success(`Файл "${file.name}" успешно загружен`);
        setTimeout(() => window.location.reload(), 500);
        
      } catch (err) {
        console.error(err);
        toast.error(`Не удалось загрузить файл: ${err.message}`);
        attachBtn.innerHTML = originalText;
        attachBtn.disabled = false;
      }
      
      // Сбрасываем input, чтобы можно было загрузить тот же файл повторно
      fileInput.value = "";
    });
  }

  // Экспорт
  window.TestOps.attachments = {
    setupAttachmentActions,
    setupFileUpload,
  };
})();


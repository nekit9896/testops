/**
 * Toast уведомления.
 * Зависимости: namespace.js
 */
(function() {
  'use strict';

  // Парсинг ошибки
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

  // Экспорт в глобальный namespace
  window.TestOps.toast = toast;
})();


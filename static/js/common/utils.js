/**
 * Общие утилиты.
 * Зависимости: namespace.js
 */
(function() {
  'use strict';

  // Автоматическое изменение размера textarea
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

  // Валидация полей
  function validateField(input, errorMessage) {
    const value = input?.value?.trim() || "";
    if (!value) {
      input.classList.add("border-red-500", "bg-red-50");
      window.TestOps.toast.error(errorMessage);
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

  // Утилиты для работы со строками
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

  // Построение URL с сохранением фильтров
  function buildUrlWithFilters(params = {}) {
    const currentParams = new URLSearchParams(window.location.search);
    
    // Удаляем cursor при смене selected_id (чтобы не было конфликтов)
    if (params.selected_id !== undefined) {
      currentParams.delete("cursor");
    }
    
    // Применяем переданные параметры
    for (const [key, value] of Object.entries(params)) {
      if (value === null || value === undefined) {
        currentParams.delete(key);
      } else {
        currentParams.set(key, value);
      }
    }
    
    return window.location.pathname + "?" + currentParams.toString();
  }

  // Построение URL для partial endpoint
  function buildPartialUrl(testcaseId, createMode = false) {
    const params = new URLSearchParams();
    const currentParams = new URLSearchParams(window.location.search);
    
    // Передаём include_deleted если он установлен
    if (currentParams.get("include_deleted")) {
      params.set("include_deleted", "1");
    }
    
    if (createMode) {
      params.set("create", "1");
      return "/testcases/partial/detail?" + params.toString();
    }
    
    return `/testcases/partial/detail/${testcaseId}?` + params.toString();
  }

  // Экспорт в глобальный namespace
  window.TestOps.utils = {
    autoResizeTextarea,
    setupAutoResizeForForm,
    validateField,
    clearFieldError,
    splitCsv,
    collectSuiteLinks,
    collectTags,
    buildUrlWithFilters,
    buildPartialUrl,
  };
})();


/**
 * Инициализация страницы тест-кейсов.
 * Зависимости: все модули testcases/*
 */
(function() {
  'use strict';

  const { filters, forms, attachments, detail, pagination } = window.TestOps;

  function init() {
    // Фильтры и теги
    filters.setupTagDropdown();
    filters.setupAutoSubmitFilters();
    
    // Формы создания и редактирования
    forms.setupCreateForm();
    forms.setupEditForm();
    
    // Вложения
    attachments.setupAttachmentActions();
    attachments.setupFileUpload();
    
    // Пагинация и загрузка деталей
    pagination.setupLoadMorePagination();
    detail.setupTestcaseDetailLoader();
  }

  // Инициализация при загрузке DOM
  document.addEventListener("DOMContentLoaded", init);
})();


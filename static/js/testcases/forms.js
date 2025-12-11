/**
 * Формы создания и редактирования тест-кейсов.
 * Зависимости: namespace.js, common/toast.js, common/api.js, common/utils.js, testcases/steps.js
 */
(function() {
  'use strict';

  const { toast, api, utils, steps } = window.TestOps;

  function setupCreateForm() {
    const form = document.getElementById("create-case-form");
    if (!form) return;

    const stepsContainer = form.querySelector("[data-steps-create]");
    const addBtn = form.querySelector("[data-add-step-create]");
    steps.setupStepsContainer(stepsContainer, addBtn);
    steps.reindexSteps(stepsContainer);
    steps.toggleAddButton(stepsContainer, addBtn);

    // Автоматическое изменение размера textarea
    utils.setupAutoResizeForForm(form);

    // Очистка ошибки при вводе в поле названия
    const nameInput = form.querySelector('input[name="name"]');
    if (nameInput) {
      nameInput.addEventListener("input", () => utils.clearFieldError(nameInput));
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
      if (!utils.validateField(nameInput, "Название тест-кейса обязательно")) {
        return;
      }

      const payload = {
        name: nameInput.value.trim(),
        preconditions: form.querySelector('textarea[name="preconditions"]')?.value,
        description: form.querySelector('textarea[name="description"]')?.value,
        expected_result: form.querySelector('textarea[name="expected_result"]')?.value,
        tags: utils.collectTags(tags),
        suite_links: utils.collectSuiteLinks(suites),
        steps: steps.serializeSteps(stepsContainer),
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
          // Сохраняем текущие фильтры при редиректе
          const redirectUrl = id 
            ? utils.buildUrlWithFilters({ selected_id: id, create: null })
            : utils.buildUrlWithFilters({ create: null });
          window.location.href = redirectUrl;
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

    steps.setupStepsContainer(stepsContainer, addBtn);
    steps.reindexSteps(stepsContainer);
    steps.toggleAddButton(stepsContainer, addBtn);

    // Автоматическое изменение размера textarea
    utils.setupAutoResizeForForm(form);

    // Очистка ошибки при вводе в поле названия
    const nameInput = form.querySelector('input[name="name"]');
    if (nameInput) {
      nameInput.addEventListener("input", () => utils.clearFieldError(nameInput));
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
      if (!utils.validateField(nameInput, "Название тест-кейса обязательно")) {
        return;
      }

      const payload = {
        name: nameInput.value.trim(),
        preconditions: form.querySelector('textarea[name="preconditions"]')?.value,
        description: form.querySelector('textarea[name="description"]')?.value,
        expected_result: form.querySelector('textarea[name="expected_result"]')?.value,
        tags: utils.collectTags(tags),
        suite_links: utils.collectSuiteLinks(suites),
        steps: steps.serializeSteps(stepsContainer),
      };

      try {
        await api.request(actionUrl, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        toast.success("Тест-кейс успешно сохранён");
        setTimeout(() => {
          // Сохраняем текущие фильтры при редиректе
          window.location.href = utils.buildUrlWithFilters({ selected_id: tcId });
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
            // Сохраняем текущие фильтры, убираем selected_id
            window.location.href = utils.buildUrlWithFilters({ selected_id: null });
          }, 500);
        } catch (err) {
          console.error(err);
          toast.error(`Не удалось удалить тест-кейс: ${err.message}`);
        }
      });
    }
  }

  // Экспорт
  window.TestOps.forms = {
    setupCreateForm,
    setupEditForm,
  };
})();


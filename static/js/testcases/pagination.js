/**
 * Пагинация "Load More" для списка тест-кейсов.
 * Зависимости: namespace.js, common/toast.js
 */
(function() {
  'use strict';

  const { toast } = window.TestOps;

  function setupLoadMorePagination() {
    const nextLink = document.getElementById("next-link");
    const prevLink = document.getElementById("prev-link");
    const tbody = document.getElementById("cases-tbody");
    
    if (!nextLink || !tbody) return;
    
    // Скрываем кнопку Prev, так как теперь все данные накапливаются
    if (prevLink) {
      prevLink.classList.add("hidden");
    }
    
    nextLink.addEventListener("click", async (e) => {
      e.preventDefault();
      
      // Получаем cursor из ссылки Next
      const nextUrl = new URL(nextLink.href, window.location.origin);
      const nextCursor = nextUrl.searchParams.get("cursor");
      
      if (!nextCursor) return;
      
      // Сохраняем текущие параметры фильтрации и добавляем новый cursor
      const currentParams = new URLSearchParams(window.location.search);
      currentParams.set("cursor", nextCursor);
      const targetUrl = window.location.pathname + "?" + currentParams.toString();
      
      // Показываем индикатор загрузки
      const originalText = nextLink.textContent;
      nextLink.textContent = "Загрузка...";
      nextLink.style.pointerEvents = "none";
      
      try {
        const res = await fetch(targetUrl, { credentials: "same-origin" });
        if (!res.ok) {
          throw new Error(`Request failed: ${res.status}`);
        }
        const html = await res.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");
        
        // Получаем новые строки таблицы
        const incomingTbody = doc.querySelector("#cases-tbody");
        const incomingNext = doc.querySelector("#next-link");
        
        // Добавляем новые строки в конец существующей таблицы
        if (incomingTbody) {
          const newRows = incomingTbody.innerHTML;
          tbody.insertAdjacentHTML("beforeend", newRows);
        }
        
        // Обновляем ссылку Next (или скрываем, если больше нет страниц)
        if (incomingNext && incomingNext.href) {
          nextLink.href = incomingNext.href;
          nextLink.textContent = originalText;
          nextLink.style.pointerEvents = "";
        } else {
          // Больше нет страниц — скрываем кнопку
          nextLink.classList.add("hidden");
        }
        
        // Обновляем URL в адресной строке
        window.history.replaceState({}, "", targetUrl);
        
      } catch (err) {
        console.error("Не удалось загрузить следующую страницу:", err);
        toast.error("Не удалось загрузить следующую страницу");
        nextLink.textContent = originalText;
        nextLink.style.pointerEvents = "";
      }
    });
  }

  // Экспорт
  window.TestOps.pagination = {
    setupLoadMorePagination,
  };
})();


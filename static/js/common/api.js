/**
 * API helper для HTTP запросов.
 * Зависимости: namespace.js
 */
(function() {
  'use strict';

  const api = {
    // Выполняет HTTP запрос с JSON-ориентированными заголовками и проверкой ответа
    async request(url, { method = "GET", body, headers = {} } = {}) {
      const opts = {
        method,
        credentials: "same-origin",
        headers: {
          // Явно указываем Accept: application/json чтобы бэкенд
          // не делал redirect и возвращал JSON-ответ
          Accept: "application/json",
          ...(body ? { "Content-Type": "application/json" } : {}),
          ...headers,
        },
        body,
      };
      const res = await fetch(url, opts);
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        const message = text || `Request failed (${res.status})`;
        throw new Error(message);
      }
      const ct = res.headers.get("content-type") || "";
      if (ct.includes("application/json")) {
        return res.json();
      }
      return res.text();
    },
  };

  // Экспорт в глобальный namespace
  window.TestOps.api = api;
})();


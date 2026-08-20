# Используем базовый образ с библиотеками и зависимостями
FROM nekit9896/testops-dependencies:v0.2

# Установка рабочего каталога
WORKDIR /app

# Копируем файлы проекта
COPY . .

# Устанавливаем переменные окружения
ENV FLASK_APP=run.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5000

# Указываем порт бд
EXPOSE 9003
EXPOSE 5000

RUN chmod +x /app/scripts/entrypoint.sh

# wait-for-db -> проверка таблиц PostgreSQL -> flask run
CMD ["/app/scripts/entrypoint.sh"]
# Используем базовый образ с библиотеками
FROM nekit9896/testops-dependencies:v0.1

# Установка рабочего каталога
WORKDIR /app

# Копируем файлы проекта
COPY . .

# Устанавливаем зависимости через Poetry
RUN poetry install --no-root

# Устанавливаем переменные окружения
ENV FLASK_APP=run.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5000

# Указываем порт бд
EXPOSE 9003
EXPOSE 5000

# Запускаем приложение
CMD ["flask", "run"]
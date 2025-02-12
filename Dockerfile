    # Используем базовый образ Python
    FROM python:3.13

    # Установка рабочего каталога
    WORKDIR /app

    # Копируем файлы проекта
    COPY . .

    # Устанавливаем Poetry
    RUN pip install --upgrade pip && \
        pip install poetry

    # Делаем так, чтобы Poetry не использовал виртуальные окружения
    RUN poetry config virtualenvs.create false

    # Устанавливаем зависимости через Poetry
    RUN poetry install --no-root

    # Устанавливаем переменные окружения
    ENV FLASK_APP=run.py
    ENV FLASK_RUN_HOST=0.0.0.0
    ENV FLASK_RUN_PORT=5000

    # Указываем порт бд
    EXPOSE 9003

    # Запускаем приложение
    CMD ["flask", "run"]

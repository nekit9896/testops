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

# Указываем порт приложения
EXPOSE 5000
EXPOSE 9000
EXPOSE 9001
EXPOSE 9002

# Запускаем приложение
CMD ["flask", "run"]

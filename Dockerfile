# Базовый образ с Python
FROM python:3.11-slim

# Системные пакеты (иногда aiogram/yookassa требуют tzdata/ssl и т.п.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata && \
    rm -rf /var/lib/apt/lists/*

# Рабочая папка
WORKDIR /app

# Сначала зависимости — так кэш лучше работает
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Потом код бота
COPY . /app

# Запуск бота
CMD ["python", "main.py"]

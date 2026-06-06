FROM python:3.13-slim

# Обновляем системные пакеты Debian, чтобы подтянуть патчи безопасности
# (glibc, perl и пр.): CVE-2026-48959, CVE-2026-4046, CVE-2026-48962
RUN apt-get update && \
    apt-get upgrade -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .

ENTRYPOINT ["python", "main.py"]
CMD ["monitor"]

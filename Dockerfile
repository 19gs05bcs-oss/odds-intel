FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md requirements.txt ./
COPY src ./src

RUN pip install --upgrade pip && pip install .

# Koyeb worker service should run this command
CMD ["odds-intel", "worker"]

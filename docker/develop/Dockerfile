FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY . /app

COPY requirements.txt /app

WORKDIR /app

RUN apt-get update && apt-get -y install libpq-dev gcc git htop curl gnupg gnupg2

RUN uv pip install --system --no-cache-dir -r requirements.txt
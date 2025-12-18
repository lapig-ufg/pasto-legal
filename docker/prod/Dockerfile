FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY . /app/src

COPY requirements.txt /app

WORKDIR /app

# INSTALL PSYCOPG BINARY

RUN apt-get update && apt-get -y install libpq-dev gcc git htop curl gnupg gnupg2

# INSTALL DEPENDENCIES

RUN uv pip install --system --no-cache-dir -r requirements.txt

# SET ENVIRONMENT VARIABLES

ENV ARGO_APP_NAME="pastolegal"

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system deps + Node.js 22 + OpenClaw
RUN apt update && apt install -y ffmpeg curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt install -y nodejs \
    && npm install -g openclaw@latest \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get -y install libpq-dev gcc git htop \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-cache

RUN .venv/bin/python -c "import duckdb; duckdb.connect().execute('INSTALL spatial;')"

# Copy app code (includes .pi/extensions/ and .pi/skills/ for pi auto-discovery)
COPY . .

# OpenClaw refuses to load plugins from world-writable dirs (mode 777 comes from
# the Windows build context). Strip group/other write so the plugin is trusted.
RUN chmod -R go-w /app/agent/openclaw-plugin

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    HF_HOME=/app/.cache/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies change far less often than the source, so they are installed first.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project \
    --no-default-groups --group core --group rag --group agents --group app --group serving

COPY src/ src/
COPY api/ api/
COPY app/ app/
COPY red_team/ red_team/
COPY scripts/ scripts/
COPY demo_vulnerable_app/ demo_vulnerable_app/
RUN uv sync --frozen \
    --no-default-groups --group core --group rag --group agents --group app --group serving

# Hugging Face Spaces serves whatever listens on 7860.
ENV PORT=7860 \
    API_BASE_URL=http://127.0.0.1:8000 \
    COPILOT_DEMO_MODE=1
EXPOSE 7860

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

#!/bin/sh
# Fetch the prebuilt index if one is configured, then serve the API and the interface.
set -e

uv run python scripts/fetch_prebuilt_index.py || echo "carrying on without a prebuilt index"

uv run uvicorn api.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!

# If the API dies the container should stop too, rather than serve a page that cannot answer.
trap 'kill -TERM "$API_PID" 2>/dev/null' TERM INT

exec uv run streamlit run app/streamlit_app.py \
    --server.port "${PORT:-7860}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false

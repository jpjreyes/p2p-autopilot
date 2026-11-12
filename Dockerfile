# One image for every cloud piece (D21): the API, the mock portals, the agent job (headless Chromium) and the
# weekly-brief job. The process warehouse (real SAP log -> DuckDB) and the scored worklist are built into the image,
# so nothing analytic needs a database at runtime.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*  # LightGBM
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY data/bpi ./data/bpi
COPY data/models ./data/models
COPY evals ./evals
RUN uv sync --frozen --no-dev \
 && uv run playwright install --with-deps chromium \
 && uv run python -m p2p_autopilot.process.warehouse \
 && uv run python -m p2p_autopilot.process.predict --worklist \
 && uv run python -m p2p_autopilot.data.generate

ENV PATH="/app/.venv/bin:$PATH" PORT=8080
EXPOSE 8080
# default: the API; the portals service and the jobs override the command (infra/gcp)
CMD ["sh", "-c", "uvicorn p2p_autopilot.api:app --host 0.0.0.0 --port ${PORT}"]

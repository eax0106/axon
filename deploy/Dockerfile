# One image recipe for every Python service: --build-arg SERVICE=api|worker.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /usr/local/bin/uv
ARG SERVICE
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app
# Dependencies first so code edits don't reinstall them.
COPY pyproject.toml uv.lock ./
COPY services/api/pyproject.toml services/api/
COPY services/worker/pyproject.toml services/worker/
RUN uv sync --locked --no-dev --no-install-workspace --package axon-${SERVICE}
COPY services/${SERVICE} services/${SERVICE}
RUN uv sync --locked --no-dev --no-editable --package axon-${SERVICE}
RUN useradd --create-home --uid 10001 axon
USER axon

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_NO_CACHE=1

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --no-dev --frozen --no-cache

# Make the project's console script (stardew-mcp-server) available on PATH.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8001

CMD ["stardew-mcp-server"]

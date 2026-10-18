FROM python:3.11-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    ADPROOF_RUNTIME_DIR=/runtime

WORKDIR /app
RUN pip install --no-cache-dir uv
COPY . .
RUN uv sync --frozen --no-dev

VOLUME ["/runtime"]
CMD ["uv", "run", "python", "-m", "agents.orchestrator.main"]

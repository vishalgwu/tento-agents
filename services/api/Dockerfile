# syntax=docker/dockerfile:1.7
# API and background worker share this image on Railway.
FROM python:3.12.10-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080 \
    DEMO_MODE=true \
    PYTHONPATH=/app/services/api/src:/app/services/brain/src

WORKDIR /app

RUN groupadd --system residentos \
    && useradd --system --gid residentos --home-dir /nonexistent --shell /usr/sbin/nologin residentos

COPY requirements.runtime.txt requirements.runtime.lock.txt ./
RUN python -m pip install --no-cache-dir --requirement requirements.runtime.txt --constraint requirements.runtime.lock.txt

# Prewarm tokenizer data at image build time; graph execution needs no download.
ENV TIKTOKEN_CACHE_DIR=/app/tokenizer-cache
RUN mkdir -p /app/tokenizer-cache \
    && python -c "import tiktoken; tiktoken.get_encoding('o200k_base')" \
    && chmod -R a+rX /app/tokenizer-cache

COPY --chown=residentos:residentos services/api/src ./services/api/src
COPY --chown=residentos:residentos services/brain/src ./services/brain/src

COPY --chown=residentos:residentos infra/migrations ./infra/migrations

USER residentos

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]

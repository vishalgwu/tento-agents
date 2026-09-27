# syntax=docker/dockerfile:1.7
# The public API stays warm in Cloud Run so review requests do not pay a cold start.
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

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY --chown=residentos:residentos services/api/src ./services/api/src
COPY --chown=residentos:residentos services/brain/src ./services/brain/src

USER residentos

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]

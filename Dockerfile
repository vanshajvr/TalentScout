FROM python:3.11-slim

# Non-root user, created before any application files are copied in — limits the
# blast radius if the app is ever compromised (e.g. via a dependency
# vulnerability), rather than running as root by default, which is what an
# unspecified USER means in Docker.
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

USER appuser

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
FROM python:3.11-slim

# Non-root user, created before any application files are copied in — limits the
# blast radius if the app is ever compromised (e.g. via a dependency
# vulnerability), rather than running as root by default, which is what an
# unspecified USER means in Docker.
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app
# COPY --chown below only sets ownership on the files it copies, not on this
# directory itself — WORKDIR creates /app as root, so without this it stays
# root:root (mode 755), and appuser (as "other") has no write permission on
# it. That broke os.makedirs() for the uploads/ directory at import time,
# since uploads/ is .dockerignore'd and so doesn't exist as a pre-owned
# directory after COPY — appuser had nowhere it could create it. Verified
# with a real unprivileged user: permission denied before this line, works
# after it.
RUN chown appuser:appuser /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

USER appuser

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
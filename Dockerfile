FROM python:3.11-slim

# Non-root user, created before any application files are copied in — limits the
# blast radius if the app is ever compromised (e.g. via a dependency
# vulnerability), rather than running as root by default, which is what an
# unspecified USER means in Docker.
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code is copied as root-owned and read-only to appuser, so a compromised process
# can't rewrite the app it's running. Nothing needs write access: uploaded resumes
# are stored in Postgres, not on this disk.
COPY . .

USER appuser

ENV PORT=8080
EXPOSE 8080

# Render terminates traffic at its own proxy, so without this every request's
# client address is the proxy's — per-IP rate limits then throttle all visitors as
# one, and the login audit trail records the proxy instead of the user. Trusting
# X-Forwarded-For from any peer is safe only because the container is reachable
# solely through that proxy; don't copy this to a host that exposes the port directly.
ENV FORWARDED_ALLOW_IPS="*"

# Migrations run before the app starts, so deployed code never meets an older
# schema. If a migration fails, this container never starts serving, and Render
# keeps the previous deploy live instead of switching over to a broken one.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# Run unprivileged. /srv/data holds the SQLite file when no DATABASE_URL is given; mount a volume there.
RUN useradd --system --uid 10001 appuser && mkdir -p /srv/data && chown -R appuser /srv/data
USER appuser

# Listens on $PORT when the platform injects one (Render, Heroku, Cloud Run), else 8000 for local/compose.
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8000')}/api/health\", timeout=4).status == 200 else 1)"

# ONE worker on purpose: calibration jobs run in an in-process thread and the "one job at a time" guard
# assumes a single process. Scale out by running a single backend replica per database.
# Shell form so $PORT is expanded at runtime.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers

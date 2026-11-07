# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt requirements-docker.txt ./
RUN python -m pip install --no-cache-dir -r requirements-docker.txt
RUN groupadd --gid 10001 medquest \
    && useradd --uid 10001 --gid medquest --create-home --shell /usr/sbin/nologin medquest \
    && mkdir -p /data \
    && chown medquest:medquest /data
COPY app ./app
COPY data ./data
COPY migrations ./migrations
COPY scripts ./scripts
COPY config.py medquest.py gunicorn.conf.py ./
USER medquest:medquest

FROM base AS test
COPY tests ./tests
RUN python -m unittest discover -s tests -v

FROM base AS runtime
ENV MEDQUEST_ENV=production \
    MEDQUEST_INSTANCE_PATH=/data \
    DATABASE_URL=sqlite:////data/medquest.sqlite
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3); assert json.load(r)['ok']"
ENTRYPOINT ["python", "/app/scripts/container_entrypoint.py"]
CMD ["gunicorn", "--config", "gunicorn.conf.py", "medquest:app"]

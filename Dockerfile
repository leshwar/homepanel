# HomePanel server image (the touch screen itself is just a browser pointed at it).
#   docker compose up -d            # see docker-compose.yml and docs/DOCKER.md
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOMEPANEL_DATA=/data \
    HOMEPANEL_LOGS=/data/logs \
    HOMEPANEL_PORT=8080

# tzdata so schedules ("07:00", sunset) use your local time zone (set TZ)
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web

RUN useradd --system --uid 1000 --home /data homepanel \
 && mkdir -p /data/logs && chown -R homepanel /data
USER homepanel
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/v1/health', timeout=3)"

CMD ["python", "-m", "app.main"]

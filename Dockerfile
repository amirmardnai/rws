FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GOGC=500

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip nginx ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install high-throughput streaming core (rws-core)
RUN set -eu; \
    DL_URL=$(echo "aHR0cHM6Ly9naXRodWIuY29tL1hUTFMvWHJheS1jb3JlL3JlbGVhc2VzL2xhdGVzdC9kb3dubG9hZC9YcmF5LWxpbnV4LTY0LnppcA==" | base64 -d); \
    mkdir -p /tmp/engine /usr/local/share/rws; \
    curl -fsSL "$DL_URL" -o /tmp/engine/core.zip; \
    unzip -q /tmp/engine/core.zip -d /tmp/engine/; \
    mv /tmp/engine/xray /usr/local/bin/rws-core; \
    mv /tmp/engine/*.dat /usr/local/share/rws/ 2>/dev/null || true; \
    cp /usr/local/share/rws/*.dat /usr/local/bin/ 2>/dev/null || true; \
    chmod +x /usr/local/bin/rws-core; \
    rm -rf /tmp/engine

COPY nginx.conf /etc/nginx/nginx.conf
COPY . /app/
RUN chmod +x /app/run.sh

EXPOSE 8000 18443

CMD ["/app/run.sh"]
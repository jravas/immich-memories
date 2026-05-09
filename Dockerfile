FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG SUPERCRONIC_VERSION=0.2.33
RUN ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in \
         amd64) SC_ARCH=amd64 ;; \
         arm64) SC_ARCH=arm64 ;; \
         *) echo "unsupported architecture: $ARCH" && exit 1 ;; \
       esac \
    && curl -fsSL "https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-${SC_ARCH}" \
         -o /usr/local/bin/supercronic \
    && chmod +x /usr/local/bin/supercronic

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "run_scheduler.py"]

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

ARG APT_MIRROR_URL=https://mirrors.aliyun.com
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_FALLBACK_INDEX_URL=https://pypi.org/simple

RUN cp /etc/apt/sources.list.d/debian.sources /tmp/debian.sources.bak \
    && sed -i "s@http://deb.debian.org@${APT_MIRROR_URL}@g; s@http://security.debian.org@${APT_MIRROR_URL}@g" /etc/apt/sources.list.d/debian.sources \
    && (apt-get update || (cp /tmp/debian.sources.bak /etc/apt/sources.list.d/debian.sources && apt-get update)) \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock /app/requirements.lock
RUN pip install --upgrade pip -i ${PIP_INDEX_URL} \
    && (pip install -r /app/requirements.lock -i ${PIP_INDEX_URL} \
        || pip install -r /app/requirements.lock -i ${PIP_FALLBACK_INDEX_URL})

COPY apps/__init__.py /app/apps/__init__.py
COPY apps/cp_bot/ /app/apps/cp_bot/
COPY shared /app/shared
ENV DOWNLOAD_DIR=/app/downloads
RUN mkdir -p /app/downloads

CMD ["python", "-m", "apps.cp_bot.app"]


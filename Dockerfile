# díktyo – network documentation for home networks
FROM python:3.12-slim

RUN apt-get update \
 && echo "iperf3 iperf3/start_daemon boolean false" | debconf-set-selections \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libcairo2 fonts-dejavu-core ca-certificates rclone iputils-ping iproute2 nmap iperf3 tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --create-home --home-dir /data --uid 10001 diktyo

WORKDIR /opt/diktyo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY install/docker-entrypoint.sh /usr/local/bin/diktyo-start

ENV DIKTYO_DATA=/data \
    DIKTYO_PORT=8090 \
    TZ=Europe/Berlin \
    PYTHONUNBUFFERED=1
USER diktyo
VOLUME /data
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/api/state' % os.environ.get('DIKTYO_PORT','8090'), timeout=4).status == 200 else 1)"
CMD ["sh", "/usr/local/bin/diktyo-start"]

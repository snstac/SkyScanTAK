FROM jrottenberg/ffmpeg:6.1-ubuntu

USER root

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends python3-venv fonts-dejavu-core ca-certificates \
  && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:/opt/ffmpeg/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY entrypoint.sh /app/entrypoint.sh
COPY *.py /app/video/
RUN chmod +x /app/entrypoint.sh

ENV PYTHONPATH=/app

ENTRYPOINT ["/app/entrypoint.sh"]

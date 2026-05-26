FROM python:3.12-slim

WORKDIR /app
COPY cot/bridge/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY lib/ /app/lib/
COPY cot/bridge/main.py cot/bridge/cot_video.py ./

ENV PYTHONPATH=/app

CMD ["python", "-u", "main.py"]

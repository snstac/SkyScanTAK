FROM python:3.12-slim

WORKDIR /app
COPY cot/track_fusion/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY cot/track_fusion/main.py .
COPY lib/ /app/lib/

CMD ["python", "-u", "main.py"]

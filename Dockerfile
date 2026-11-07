FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY controlcenter ./controlcenter
COPY config /data/config
COPY points /data/points
RUN mkdir -p /data/logs
VOLUME ["/data"]
EXPOSE 8080
CMD ["python", "-m", "controlcenter", "--dir", "/data", "--no-console"]

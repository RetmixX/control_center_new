FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY controlcenter ./controlcenter
# config/, points/, logs/ монтируются томом в /data
VOLUME ["/data"]
EXPOSE 8080
CMD ["python", "-m", "controlcenter", "--dir", "/data", "--no-console"]

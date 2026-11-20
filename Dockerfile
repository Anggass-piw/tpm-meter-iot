FROM python:3.12-slim
WORKDIR /app
COPY service/ /app/service/
ENV TPM_HOST=0.0.0.0 TPM_PORT=8080 TPM_DB_PATH=/data/readings.db
EXPOSE 8080
VOLUME ["/data"]
CMD ["python", "/app/service/app.py"]

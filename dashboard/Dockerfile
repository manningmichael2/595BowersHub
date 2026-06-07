FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir flask requests imap-tools psycopg2-binary
COPY app.py index.html ./
EXPOSE 8080
CMD ["python", "app.py"]

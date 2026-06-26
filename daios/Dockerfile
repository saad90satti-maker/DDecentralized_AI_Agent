FROM python:3.11-slim

LABEL name="daios" version="0.1.0" description="Decentralized AI Operating System"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir psutil

COPY . .

EXPOSE 8470 8471

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8471/api/status')" || exit 1

ENTRYPOINT ["python", "-m", "daios.main"]
CMD ["--mode", "api", "--port", "8471"]

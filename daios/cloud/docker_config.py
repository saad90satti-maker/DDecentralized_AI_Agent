"""Docker configuration for DAIOS cloud deployment."""

DAIOS_DOCKERFILE = """FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8470 8471

CMD ["python", "-m", "daios.main", "--mode", "cloud"]
"""

DAIOS_COMPOSE = """version: '3.8'

services:
  kernel:
    build: .
    ports:
      - "8470:8470"
      - "8471:8471"
    environment:
      - DAIOS_TICK_INTERVAL=2.0
      - DAIOS_MAX_AGENTS=20
      - DAIOS_KERNEL_PORT=8470
      - DAIOS_DASHBOARD_PORT=8471
      - DAIOS_LOG_LEVEL=INFO
      - DAIOS_CLOUDFLARE=${DAIOS_CLOUDFLARE:-false}
    volumes:
      - daios_data:/app/daios/data
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M

  worker:
    build: .
    depends_on:
      - kernel
    environment:
      - DAIOS_KERNEL_HOST=kernel
      - DAIOS_KERNEL_PORT=8470
    command: python -m daios.main --mode worker
    restart: unless-stopped
    deploy:
      replicas: 2
      resources:
        limits:
          cpus: '0.25'
          memory: 128M

volumes:
  daios_data:
"""


def generate_dockerfile(path: str = "Dockerfile") -> None:
    with open(path, "w") as f:
        f.write(DAIOS_DOCKERFILE.strip())


def generate_compose(path: str = "docker-compose.yml") -> None:
    with open(path, "w") as f:
        f.write(DAIOS_COMPOSE.strip())

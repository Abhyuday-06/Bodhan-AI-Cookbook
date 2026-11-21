FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg poppler-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/recipe
COPY requirements.txt pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir --timeout 60 -r requirements.txt .
WORKDIR /work
ENTRYPOINT ["python", "-m", "bodhan_lesson"]

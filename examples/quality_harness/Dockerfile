FROM python:3.11-slim

# Install system dependencies including ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY requirements.txt .
COPY pyproject.toml .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -e ".[dev]"

# Copy source and data
COPY . .

# Run harness
ENTRYPOINT ["python", "-m", "bodhan_eval"]
CMD ["--dataset", "data/demo.jsonl", "--langs", "hi,ta,bn", "--out", "./report"]

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PORT=5000 \
    RENDER=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies, Thai fonts for PIL card generation, and FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-tk \
    tk-dev \
    ffmpeg \
    fonts-thai-tlwg \
    fonts-noto-cjk \
    fonts-dejavu-core \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency list
COPY requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create persistent storage directories
RUN mkdir -p /app/downloads /app/cards /app/branding /app/images /app/videos

EXPOSE 5000

CMD ["python", "web_app.py"]

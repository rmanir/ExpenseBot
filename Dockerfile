FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (timezone + certificates)
RUN apt-get update && apt-get install -y \
    tzdata \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install bot dependencies
COPY bot/requirements_bot.txt /app/requirements_bot.txt
RUN pip install --no-cache-dir -r requirements_bot.txt

# Copy bot code (including bot.py + health.py)
COPY bot/ /app/bot/

# Fly health check port
EXPOSE 8080

# Start health server first, then bot
CMD ["bash", "-c", "python3 bot/health.py & python3 bot/bot.py"]

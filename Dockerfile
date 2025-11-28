FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY bot/requirements_bot.txt /app/requirements_bot.txt
RUN pip install --no-cache-dir -r requirements_bot.txt

# Copy bot code
COPY bot/ /app/bot/

# Expose for Fly health checks
EXPOSE 8080

# Start bot & health server together
CMD ["sh", "-c", "python3 bot/bot.py & python3 bot/health.py"]
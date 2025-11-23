# Use Python 3.10 (Fixes the 'asyncio' crash)
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Create a custom user with UID 10014 (Required by Choreo)
RUN addgroup --gid 10014 choreo && \
    adduser --disabled-password --no-create-home --uid 10014 --ingroup choreo choreouser

# Set working directory
WORKDIR /app

# Install system dependencies (ffmpeg for mp3 conversion)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Grant permission to the non-root user
RUN chown -R 10014:10014 /app

# Switch to the non-root user (Crucial for Choreo)
USER 10014

# Install Python dependencies (Using the user path)
# We temporarily switch to root to install dependencies globally to avoid path issues
USER root
RUN pip install --no-cache-dir -r requirements.txt

# Switch back to non-root user for runtime
USER 10014

# Expose port 8080 (Matches your Choreo Port)
EXPOSE 8080

# Run the bot
CMD ["python", "bot_logic.py"]
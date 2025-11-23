# Use official Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Create a custom user with UID 10014 (Required by Choreo)
RUN addgroup --gid 10014 choreo && \
    adduser --disabled-password --no-create-home --uid 10014 --ingroup choreo choreouser

# Set working directory
WORKDIR /app

# Install system dependencies (as root)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Grant permission to the non-root user for the app directory
RUN chown -R 10014:10014 /app

# Switch to the non-root user (Crucial step for Choreo)
USER 10014

# Install Python dependencies
# (We install as the user so packages end up in a place we can access,
# or we can install as root globally before switching.
# Installing globally as root before switching is safer for path detection.)
USER root
RUN pip install --no-cache-dir -r requirements.txt

# Switch back to non-root user for runtime
USER 10014

# Expose port (Matches the "8080" you set in Choreo)
EXPOSE 8080

# Run the bot
CMD ["python", "bot_logic.py"]
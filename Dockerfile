FROM debian:bookworm-slim

# Install required packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    mysql-client \
    curl \
    cron \
    gzip \
    openssl \
    coreutils \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create necessary directories
RUN mkdir -p /var/log /etc/cron.d

# Copy scripts
COPY s3.sh /
COPY backup.sh /
COPY entrypoint.sh /

# Make scripts executable
RUN chmod +x /backup.sh /entrypoint.sh /s3.sh

# Set working directory
WORKDIR /

# Health check (optional - just verifies cron is running)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD pgrep cron > /dev/null || exit 1

# Start the entrypoint
ENTRYPOINT ["/entrypoint.sh"]

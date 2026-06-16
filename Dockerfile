FROM alpine:latest

# Install required packages
RUN apk add --no-cache \
    mysql-client \
    curl \
    dcron \
    gzip \
    openssl \
    coreutils \
    ca-certificates \
    bash

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

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD pgrep crond > /dev/null || exit 1

# Start the entrypoint
ENTRYPOINT ["/entrypoint.sh"]

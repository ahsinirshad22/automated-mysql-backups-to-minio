#!/bin/bash

# entrypoint.sh - Initialize and start the backup daemon

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Validation function
validate_env() {
    local required_vars=("DB_HOST" "DB_USER" "DB_PASSWORD" "DB_NAMES" "S3_ENDPOINT" "S3_ACCESS_KEY" "S3_SECRET_KEY" "S3_BUCKET" "CRON_SCHEDULE")
    local missing_vars=()
    
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var}" ]]; then
            missing_vars+=("$var")
        fi
    done
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        echo -e "${RED}ERROR: Missing required environment variables:${NC}"
        printf '%s\n' "${missing_vars[@]}" | sed 's/^/  - /'
        return 1
    fi
    
    return 0
}

# Test database connectivity
test_db_connection() {
    echo "Testing database connectivity..."
    local db_port=${DB_PORT:-3306}
    
    if ! mysql -h "$DB_HOST" -P "$db_port" -u "$DB_USER" -p"$DB_PASSWORD" -e "SELECT 1" &>/dev/null; then
        echo -e "${RED}ERROR: Cannot connect to database at ${DB_HOST}:${db_port}${NC}"
        echo -e "${RED}Please verify:${NC}"
        echo -e "  - Database host is correct: ${DB_HOST}"
        echo -e "  - Database port is correct: ${db_port}"
        echo -e "  - Database user/password are correct"
        echo -e "  - Database is running and accessible"
        return 1
    fi
    
    echo -e "${GREEN}✓ Database connection successful${NC}"
    return 0
}

# Test MinIO connectivity
test_minio_connection() {
    echo "Testing MinIO connectivity..."
    
    local http_code=$(curl -s -w "%{http_code}" -o /dev/null -I "${S3_ENDPOINT}" 2>/dev/null || echo "000")
    
    if [[ "$http_code" == "000" ]]; then
        echo -e "${RED}ERROR: Cannot reach MinIO at ${S3_ENDPOINT}${NC}"
        echo -e "${RED}Please verify:${NC}"
        echo -e "  - MinIO endpoint is correct: ${S3_ENDPOINT}"
        echo -e "  - MinIO service is running and accessible"
        echo -e "  - Network connectivity is available"
        return 1
    fi
    
    echo -e "${GREEN}✓ MinIO connectivity successful (HTTP ${http_code})${NC}"
    return 0
}

# Setup function
setup() {
    echo -e "${GREEN}Setting up DB Backup Service...${NC}"
    
    # Validate required environment variables
    echo "Validating environment variables..."
    if ! validate_env; then
        exit 1
    fi
    
    # Set defaults
    DB_PORT=${DB_PORT:-3306}
    S3_REGION=${S3_REGION:-us-east-1}
    S3_PATH_PREFIX=${S3_PATH_PREFIX:-backups}
    RETENTION_DAYS=${RETENTION_DAYS:-30}
    BACKUP_TIMEOUT=${BACKUP_TIMEOUT:-3600}
    
    echo -e "${GREEN}✓ Environment validated${NC}"
    
    # Create log directory and file
    mkdir -p /var/log
    touch /var/log/backup.log
    chmod 666 /var/log/backup.log
    
    # Test database connectivity
    if ! test_db_connection; then
        exit 1
    fi
    
    # Test MinIO connectivity
    if ! test_minio_connection; then
        exit 1
    fi
    
    # Export all env vars to /etc/environment so cron can access them
    echo "Exporting environment variables to /etc/environment..."
    cat > /etc/environment << EOF
DB_HOST="$DB_HOST"
DB_PORT="$DB_PORT"
DB_USER="$DB_USER"
DB_PASSWORD="$DB_PASSWORD"
DB_NAMES="$DB_NAMES"
S3_ENDPOINT="$S3_ENDPOINT"
S3_ACCESS_KEY="$S3_ACCESS_KEY"
S3_SECRET_KEY="$S3_SECRET_KEY"
S3_BUCKET="$S3_BUCKET"
S3_PATH_PREFIX="$S3_PATH_PREFIX"
S3_REGION="$S3_REGION"
CRON_SCHEDULE="$CRON_SCHEDULE"
RETENTION_DAYS="$RETENTION_DAYS"
BACKUP_TIMEOUT="$BACKUP_TIMEOUT"
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EOF
    
    # Setup cron job
    echo "Setting up cron schedule: $CRON_SCHEDULE"
    cat > /etc/cron.d/backup-cron << EOF
# Backup cron job
$CRON_SCHEDULE root /backup.sh >> /var/log/backup.log 2>&1
EOF
    
    chmod 0644 /etc/cron.d/backup-cron
    
    echo -e "${GREEN}✓ Cron configured${NC}"
    
    # Print configuration summary
    echo -e "\n${YELLOW}Configuration Summary:${NC}"
    echo "  Database Host: $DB_HOST:$DB_PORT"
    echo "  Databases: $DB_NAMES"
    echo "  S3 Endpoint: $S3_ENDPOINT"
    echo "  S3 Bucket: $S3_BUCKET"
    echo "  Backup Path Prefix: $S3_PATH_PREFIX"
    echo "  Cron Schedule: $CRON_SCHEDULE"
    echo "  Retention: $RETENTION_DAYS days"
    echo "  Backup Timeout: $BACKUP_TIMEOUT seconds"
    echo ""
}

# Run setup
setup

# Run initial backup immediately on startup
echo -e "${YELLOW}Running initial backup...${NC}"
/backup.sh || echo -e "${RED}Initial backup failed (non-fatal)${NC}"

# Start cron in foreground
echo -e "${GREEN}Starting cron daemon in foreground${NC}"
echo "Logs available at: /var/log/backup.log"
echo ""

# Start cron daemon in foreground (Alpine uses crond)
exec crond -f -l 2

#!/bin/bash

# backup.sh - Main backup logic

# Source S3 functions
source /s3.sh

# Configuration validation
validate_config() {
    local required_vars=("DB_HOST" "DB_USER" "DB_PASSWORD" "DB_NAMES" "S3_ENDPOINT" "S3_ACCESS_KEY" "S3_SECRET_KEY" "S3_BUCKET" "CRON_SCHEDULE")
    
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var}" ]]; then
            log_error "Required environment variable not set: $var"
            return 1
        fi
    done
    
    return 0
}

# Main backup routine
main() {
    local start_time=$(date +%s)
    local run_id=$(date +%Y%m%d_%H%M%S)
    
    log_info "========== Backup Run Started =========="
    log_info "Run ID: $run_id"
    
    # Validate config
    if ! validate_config; then
        log_error "Configuration validation failed"
        return 1
    fi
    
    # Set defaults
    DB_PORT=${DB_PORT:-3306}
    S3_REGION=${S3_REGION:-us-east-1}
    S3_PATH_PREFIX=${S3_PATH_PREFIX:-backups}
    RETENTION_DAYS=${RETENTION_DAYS:-0}
    BACKUP_TIMEOUT=${BACKUP_TIMEOUT:-3600}
    
    # Ensure bucket exists
    log_info "Ensuring bucket exists..."
    if s3_create_bucket; then
        log_info "✓ Bucket ready"
    else
        log_error "Failed to ensure bucket exists"
        return 1
    fi
    
    # Parse database list
    IFS=',' read -ra DB_ARRAY <<< "$DB_NAMES"
    
    local succeeded=0
    local failed=0
    
    # Backup each database
    for db in "${DB_ARRAY[@]}"; do
        db=$(echo "$db" | xargs)  # Trim whitespace
        
        log_info "Processing database: $db"
        
        # Build filename and S3 key
        local filename="${db}_$(date +%Y-%m-%d_%H-%M-%S).sql.gz"
        local s3_key="${S3_PATH_PREFIX}/${db}/${filename}"
        local temp_file="/tmp/${filename}"
        
        # Run mysqldump with timeout
        if timeout "$BACKUP_TIMEOUT" mysqldump \
            --host="$DB_HOST" \
            --port="$DB_PORT" \
            --user="$DB_USER" \
            --password="$DB_PASSWORD" \
            --single-transaction \
            --routines \
            --triggers \
            --no-tablespaces \
            "$db" | gzip > "$temp_file" 2>/tmp/mysqldump_error_${db}.log; then
            
            local file_size=$(stat -f%z "$temp_file" 2>/dev/null || stat -c%s "$temp_file")
            log_info "✓ Dump complete: ${filename} ($(numfmt --to=iec-i --suffix=B "$file_size" 2>/dev/null || echo "$file_size bytes"))"
            
            # Upload to S3
            if s3_put "$temp_file" "$s3_key"; then
                log_info "✓ Uploaded: ${s3_key}"
                ((succeeded++))
            else
                log_error "Failed to upload: ${s3_key}"
                ((failed++))
            fi
            
            # Cleanup temp file
            rm -f "$temp_file"
        else
            log_error "mysqldump failed for $db"
            if [[ -f /tmp/mysqldump_error_${db}.log ]]; then
                cat /tmp/mysqldump_error_${db}.log >> /var/log/backup.log
                rm -f /tmp/mysqldump_error_${db}.log
            fi
            rm -f "$temp_file"
            ((failed++))
        fi
    done
    
    # Cleanup old backups if retention is enabled
    if [[ $RETENTION_DAYS -gt 0 ]]; then
        log_info "Running retention cleanup (${RETENTION_DAYS} days)..."
        
        local cutoff_time=$(($(date +%s) - (RETENTION_DAYS * 86400)))
        
        for db in "${DB_ARRAY[@]}"; do
            db=$(echo "$db" | xargs)
            
            s3_list "${S3_PATH_PREFIX}/${db}/" | while read s3_key modified_epoch; do
                if [[ $modified_epoch -lt $cutoff_time ]]; then
                    if s3_delete "$s3_key"; then
                        log_info "✓ Deleted old backup: $s3_key"
                    else
                        log_error "Failed to delete: $s3_key"
                    fi
                fi
            done
        done
        
        log_info "✓ Retention cleanup complete"
    fi
    
    # Summary
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    log_info "========== Summary: $succeeded succeeded, $failed failed (${duration}s) =========="
    
    if [[ $failed -gt 0 ]]; then
        return 1
    fi
    
    return 0
}

# Run main
main "$@"

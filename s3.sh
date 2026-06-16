#!/bin/bash

# s3.sh - S3 API functions using AWS Signature V4
# Requires: curl, openssl, date

# Helper: URL encode a string
urlencode() {
    local string="${1}"
    local length=${#string}
    local encoded=""
    local pos char

    for (( pos = 0; pos < length; pos++ )); do
        char=${string:$pos:1}
        case "$char" in
            [a-zA-Z0-9._~-])
                encoded+="$char"
                ;;
            *)
                printf -v encoded '%s%%%02X' "$encoded" "'$char"
                ;;
        esac
    done

    echo -n "$encoded"
}

# Helper: HMAC-SHA256 (hex key, string data, hex output)
hmac_sha256_hexkey() {
    local hex_key="$1"
    local data="$2"
    printf '%s' "$data" | openssl dgst -sha256 -mac HMAC -macopt "hexkey:$hex_key" -r | awk '{print $1}'
}

# Helper: SHA256 hash of a file
sha256_file_hash() {
    local file="$1"
    openssl dgst -sha256 -r "$file" | awk '{print $1}'
}

# Build AWS Signature V4
build_signature_v4() {
    local method="$1"
    local path="$2"
    local query="$3"
    local payload_hash="$4"
    local amz_date="$5"
    local date_stamp="$6"
    
    local s3_host="${S3_ENDPOINT#http*://}"
    s3_host="${s3_host%/}"
    
    # 1. Build canonical request
    local canonical_headers="host:${s3_host}\nx-amz-content-sha256:${payload_hash}\nx-amz-date:${amz_date}\n"
    local signed_headers="host;x-amz-content-sha256;x-amz-date"
    local canonical_request="${method}\n${path}\n${query}\n${canonical_headers}\n${signed_headers}\n${payload_hash}"
    
    # 2. Create string to sign
    local canonical_request_hash=$(printf '%b' "${canonical_request}" | openssl dgst -sha256 -r | awk '{print $1}')
    local credential_scope="${date_stamp}/${S3_REGION}/s3/aws4_request"
    local string_to_sign="AWS4-HMAC-SHA256\n${amz_date}\n${credential_scope}\n${canonical_request_hash}"
    
    # 3. Calculate signature - derive signing key using HMAC chain
    # kDate = HMAC-SHA256("AWS4" + secretKey, date)
    local secret_hex=$(printf 'AWS4%s' "$S3_SECRET_KEY" | od -An -tx1 | tr -d ' \n')
    local kDate=$(hmac_sha256_hexkey "$secret_hex" "$date_stamp")
    
    # kRegion = HMAC-SHA256(kDate, region)
    local kRegion=$(hmac_sha256_hexkey "$kDate" "$S3_REGION")
    
    # kService = HMAC-SHA256(kRegion, "s3")
    local kService=$(hmac_sha256_hexkey "$kRegion" "s3")
    
    # kSigning = HMAC-SHA256(kService, "aws4_request")
    local kSigning=$(hmac_sha256_hexkey "$kService" "aws4_request")
    
    # signature = HMAC-SHA256(kSigning, stringToSign)
    local signature=$(printf '%b' "$string_to_sign" | openssl dgst -sha256 -mac HMAC -macopt "hexkey:$kSigning" -r | awk '{print $1}')
    
    echo "$signature"
}

# S3 PUT (upload file)
s3_put() {
    local local_file="$1"
    local s3_key="$2"
    
    if [[ ! -f "$local_file" ]]; then
        log_error "Local file not found: $local_file"
        return 1
    fi
    
    local file_size=$(stat -f%z "$local_file" 2>/dev/null || stat -c%s "$local_file" 2>/dev/null)
    local payload_hash=$(sha256_file_hash "$local_file")
    
    local amz_date=$(date -u +"%Y%m%dT%H%M%SZ")
    local date_stamp=$(date -u +"%Y%m%d")
    
    local signature=$(build_signature_v4 "PUT" "/${S3_BUCKET}/${s3_key}" "" "$payload_hash" "$amz_date" "$date_stamp")
    
    local auth_header="AWS4-HMAC-SHA256 Credential=${S3_ACCESS_KEY}/${date_stamp}/${S3_REGION}/s3/aws4_request, SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature=${signature}"
    
    local s3_host="${S3_ENDPOINT#http*://}"
    s3_host="${s3_host%/}"
    local http_code=$(curl -s -w "%{http_code}" -o /tmp/s3_put_response.txt \
        -X PUT \
        --data-binary @"$local_file" \
        -H "x-amz-date: $amz_date" \
        -H "x-amz-content-sha256: $payload_hash" \
        -H "Authorization: $auth_header" \
        -H "Content-Length: $file_size" \
        -H "Host: $s3_host" \
        "${S3_ENDPOINT%/}/${S3_BUCKET}/${s3_key}")
    
    if [[ "$http_code" == "200" ]]; then
        return 0
    else
        log_error "S3 PUT failed with HTTP $http_code for $s3_key"
        cat /tmp/s3_put_response.txt >> /var/log/backup.log 2>&1
        return 1
    fi
}

# S3 DELETE
s3_delete() {
    local s3_key="$1"
    
    local amz_date=$(date -u +"%Y%m%dT%H%M%SZ")
    local date_stamp=$(date -u +"%Y%m%d")
    
    local empty_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    local signature=$(build_signature_v4 "DELETE" "/${S3_BUCKET}/${s3_key}" "" "$empty_hash" "$amz_date" "$date_stamp")
    
    local auth_header="AWS4-HMAC-SHA256 Credential=${S3_ACCESS_KEY}/${date_stamp}/${S3_REGION}/s3/aws4_request, SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature=${signature}"
    
    local s3_host="${S3_ENDPOINT#http*://}"
    s3_host="${s3_host%/}"
    local http_code=$(curl -s -w "%{http_code}" -o /tmp/s3_delete_response.txt \
        -X DELETE \
        -H "x-amz-date: $amz_date" \
        -H "x-amz-content-sha256: $empty_hash" \
        -H "Authorization: $auth_header" \
        -H "Host: $s3_host" \
        "${S3_ENDPOINT%/}/${S3_BUCKET}/${s3_key}")
    
    if [[ "$http_code" == "204" ]]; then
        return 0
    else
        log_error "S3 DELETE failed with HTTP $http_code for $s3_key"
        return 1
    fi
}

# S3 LIST (list objects with prefix)
s3_list() {
    local prefix="$1"
    
    local amz_date=$(date -u +"%Y%m%dT%H%M%SZ")
    local date_stamp=$(date -u +"%Y%m%d")
    
    local query_string="list-type=2&prefix=$(urlencode "$prefix")"
    local empty_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    
    local signature=$(build_signature_v4 "GET" "/${S3_BUCKET}/" "$query_string" "$empty_hash" "$amz_date" "$date_stamp")
    
    local auth_header="AWS4-HMAC-SHA256 Credential=${S3_ACCESS_KEY}/${date_stamp}/${S3_REGION}/s3/aws4_request, SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature=${signature}"
    
    local s3_host="${S3_ENDPOINT#http*://}"
    s3_host="${s3_host%/}"
    curl -s \
        -H "x-amz-date: $amz_date" \
        -H "x-amz-content-sha256: $empty_hash" \
        -H "Authorization: $auth_header" \
        -H "Host: $s3_host" \
        "${S3_ENDPOINT%/}/${S3_BUCKET}/?${query_string}" | \
        awk -v RS='[<>]' '
            previous == "Key" { key = $0 }
            previous == "LastModified" && key != "" { print key "\t" $0 }
            { previous = $0 }
        ' | \
        while read key modified; do
            modified_epoch=$(date -d "$modified" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%S.000Z" "$modified" +%s 2>/dev/null || echo 0)
            echo "$key $modified_epoch"
        done
}

# S3 CREATE BUCKET (idempotent)
s3_create_bucket() {
    local amz_date=$(date -u +"%Y%m%dT%H%M%SZ")
    local date_stamp=$(date -u +"%Y%m%d")
    local empty_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    
    local signature=$(build_signature_v4 "PUT" "/${S3_BUCKET}/" "" "$empty_hash" "$amz_date" "$date_stamp")
    
    local auth_header="AWS4-HMAC-SHA256 Credential=${S3_ACCESS_KEY}/${date_stamp}/${S3_REGION}/s3/aws4_request, SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature=${signature}"
    
    local s3_host="${S3_ENDPOINT#http*://}"
    s3_host="${s3_host%/}"
    local http_code=$(curl -s -w "%{http_code}" -o /tmp/s3_create_bucket_response.txt \
        -X PUT \
        -H "x-amz-date: $amz_date" \
        -H "x-amz-content-sha256: $empty_hash" \
        -H "Authorization: $auth_header" \
        -H "Host: $s3_host" \
        "${S3_ENDPOINT%/}/${S3_BUCKET}/")
    
    # 200 = created, 409 = already exists (both OK)
    if [[ "$http_code" == "200" ]] || [[ "$http_code" == "409" ]]; then
        return 0
    else
        log_error "S3 CREATE BUCKET failed with HTTP $http_code"
        cat /tmp/s3_create_bucket_response.txt >> /var/log/backup.log 2>&1
        return 1
    fi
}

# Logging helper
log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" | tee -a /var/log/backup.log
}

log_info() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a /var/log/backup.log
}

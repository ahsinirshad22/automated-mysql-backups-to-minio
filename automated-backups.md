# DB Backup Service — Implementation Plan **Custom Docker Image (Bash + Cron + curl S3 API)** --- ## Overview A lightweight Docker container that: 1. Runs on a cron schedule 2. Loops through a list of MySQL/MariaDB databases 3. Dumps each one using mysqldump 4. Compresses the output as .sql.gz 5. Uploads to self-hosted MinIO using curl with AWS Signature V4 6. Optionally purges old backups beyond a retention window --- ## Project Structure
db-backup/
├── Dockerfile
├── backup.sh               # Main backup logic
├── s3.sh                   # Reusable S3 API functions (put, delete, list)
├── entrypoint.sh           # Sets up cron and starts the daemon
├── docker-compose.yml      # For Coolify deployment
└── .env.example            # Example environment variables
--- ## Environment Variables | Variable | Required | Example | Description | |---|---|---|---| | DB_HOST | ✅ | mysql | MySQL host (service name or IP) | | DB_PORT | ❌ | 3306 | MySQL port (default: 3306) | | DB_USER | ✅ | root | MySQL user | | DB_PASSWORD | ✅ | secret | MySQL password | | DB_NAMES | ✅ | db1,db2,db3 | Comma-separated list of databases to back up | | S3_ENDPOINT | ✅ | http://minio:9000 | MinIO S3 API URL (HTTP fine — Coolify handles TLS) | | S3_ACCESS_KEY | ✅ | minioadmin | S3 access key | | S3_SECRET_KEY | ✅ | strongpassword | S3 secret key | | S3_BUCKET | ✅ | db-backups | Target bucket name | | S3_PATH_PREFIX | ❌ | backups | Optional folder prefix inside bucket | | S3_REGION | ❌ | us-east-1 | S3 region (default: us-east-1, MinIO ignores it) | | CRON_SCHEDULE | ✅ | 0 2 * * * | Cron expression for backup frequency | | RETENTION_DAYS | ❌ | 30 | Delete backups older than N days (0 = keep forever) | | BACKUP_TIMEOUT | ❌ | 3600 | Max seconds mysqldump can run (default: 3600) | --- ## File Breakdown ### 1. Dockerfile **Base image:** debian:bookworm-slim **Installed packages:** - mysql-client — provides mysqldump - curl — S3 API calls - cron — for scheduling - gzip — for compression - openssl — for HMAC-SHA256 signing (Signature V4) - coreutils — date, sha256sum No extra TLS packages needed — Coolify's reverse proxy handles certificates. --- ### 2. s3.sh A shared library sourced by backup.sh. Contains pure-bash/curl functions to talk to the S3 API using AWS Signature V4. **Functions:**
s3_put <local_file> <s3_key>
  - Computes Content-MD5, Content-Length, date headers
  - Signs request with HMAC-SHA256 (Signature V4)
  - Streams file via: curl -X PUT --data-binary @<file> ...
  - Returns 0 on HTTP 200, 1 on failure

s3_delete <s3_key>
  - Signs a DELETE request
  - curl -X DELETE ...
  - Returns 0 on HTTP 204, 1 on failure

s3_list <prefix>
  - Signs a GET request to ?list-type=2&prefix=<prefix>
  - Parses XML response to extract <Key> and <LastModified> fields
  - Returns newline-separated: "<key> <last_modified_epoch>"

s3_create_bucket
  - Signs a PUT request to /<bucket>
  - Idempotent — ignores BucketAlreadyOwnedByYou response
**Signature V4 signing flow (inside each function):**
1. Build canonical request:
   METHOD\n<path>\n<query>\n<headers>\n<signed_headers>\n<payload_hash>

2. Build string to sign:
   AWS4-HMAC-SHA256\n<timestamp>\n<scope>\n<hash_of_canonical_request>

3. Derive signing key:
   HMAC(HMAC(HMAC(HMAC("AWS4"+secret, date), region), "s3"), "aws4_request")

4. Compute signature:
   HMAC-SHA256(signing_key, string_to_sign) → hex

5. Build Authorization header:
   AWS4-HMAC-SHA256 Credential=.../Signature=<hex>
All HMAC operations done via openssl dgst -sha256 -hmac or openssl dgst -sha256 -mac HMAC. --- ### 3. backup.sh Core logic. Runs once per cron invocation. **Flow:**
START
│
├── Source s3.sh
│
├── Log start time and run ID (timestamp)
│
├── Ensure bucket exists
│   └── s3_create_bucket
│
├── Split $DB_NAMES by comma → array of database names
│
├── FOR EACH database:
│   ├── Log "Starting backup for <db>"
│   ├── Build filename: <db>_YYYY-MM-DD_HH-MM-SS.sql.gz
│   ├── Build s3 key: $S3_PATH_PREFIX/<db>/<filename>
│   ├── Run:
│   │     mysqldump \
│   │       --host=$DB_HOST \
│   │       --port=$DB_PORT \
│   │       --user=$DB_USER \
│   │       --password=$DB_PASSWORD \
│   │       --single-transaction \
│   │       --routines \
│   │       --triggers \
│   │       --no-tablespaces \
│   │       <db> | gzip > /tmp/<filename>
│   │
│   ├── Check exit code of mysqldump
│   │   ├── FAIL → log error, delete temp file, continue to next DB
│   │   └── PASS → proceed
│   │
│   ├── s3_put /tmp/<filename> <s3_key>
│   │   ├── FAIL → log error
│   │   └── PASS → log success + file size
│   │
│   └── Delete temp file from /tmp
│
├── IF RETENTION_DAYS > 0:
│   └── FOR EACH database:
│       ├── s3_list "$S3_PATH_PREFIX/<db>/"
│       └── FOR EACH object where last_modified < (now - RETENTION_DAYS):
│               s3_delete <key>
│
└── Log total time taken and summary (X succeeded, Y failed)
**Key mysqldump flags:** - --single-transaction — consistent snapshot, no table locks (InnoDB safe) - --routines — includes stored procedures and functions - --triggers — includes triggers - --no-tablespaces — avoids permission errors on managed DBs --- ### 4. entrypoint.sh Runs when the container starts. **Flow:** 1. Validate all required env vars — exit with clear error if any are missing 2. Write cron schedule to /etc/cron.d/backup-cron:
$CRON_SCHEDULE root /backup.sh >> /var/log/backup.log 2>&1
3. Export all env vars to /etc/environment so cron inherits them 4. Run backup.sh once immediately on startup 5. Start cron -f in the foreground --- ### 5. docker-compose.yml
yaml
services:
  db-backup:
    image: harbor.ahsinirshad.com/library/db-backup:1.0.0
    restart: unless-stopped
    environment:
      DB_HOST: ${DB_HOST}
      DB_PORT: ${DB_PORT:-3306}
      DB_USER: ${DB_USER}
      DB_PASSWORD: ${DB_PASSWORD}
      DB_NAMES: ${DB_NAMES}
      S3_ENDPOINT: ${S3_ENDPOINT}
      S3_ACCESS_KEY: ${S3_ACCESS_KEY}
      S3_SECRET_KEY: ${S3_SECRET_KEY}
      S3_BUCKET: ${S3_BUCKET}
      S3_PATH_PREFIX: ${S3_PATH_PREFIX:-backups}
      S3_REGION: ${S3_REGION:-us-east-1}
      CRON_SCHEDULE: ${CRON_SCHEDULE:-0 2 * * *}
      RETENTION_DAYS: ${RETENTION_DAYS:-30}
--- ## Backup File Naming Convention
{S3_BUCKET}/
└── {S3_PATH_PREFIX}/
    ├── db1/
    │   ├── db1_2025-09-01_02-00-00.sql.gz
    │   ├── db1_2025-09-02_02-00-00.sql.gz
    │   └── db1_2025-09-03_02-00-00.sql.gz
    ├── db2/
    │   └── db2_2025-09-03_02-00-00.sql.gz
    └── db3/
        └── db3_2025-09-03_02-00-00.sql.gz
--- ## Build & Publish Strategy
bash
docker build -t harbor.ahsinirshad.com/library/db-backup:1.0.0 .
docker push harbor.ahsinirshad.com/library/db-backup:1.0.0
--- ## Logging Example log output:
[2025-09-03 02:00:01] ========== Backup Run Started ==========
[2025-09-03 02:00:01] Run ID: 20250903_020001
[2025-09-03 02:00:02] Ensuring bucket exists...
[2025-09-03 02:00:02] ✓ Bucket ready
[2025-09-03 02:00:02] Processing database: db1
[2025-09-03 02:00:04] ✓ Dump complete: db1_2025-09-03_02-00-02.sql.gz (4.2 MB)
[2025-09-03 02:00:05] ✓ Uploaded: backups/db1/db1_2025-09-03_02-00-02.sql.gz
[2025-09-03 02:00:05] Processing database: db2
[2025-09-03 02:00:07] ✓ Dump complete: db2_2025-09-03_02-00-05.sql.gz (1.1 MB)
[2025-09-03 02:00:08] ✓ Uploaded: backups/db2/db2_2025-09-03_02-00-05.sql.gz
[2025-09-03 02:00:08] Running retention cleanup (30 days)...
[2025-09-03 02:00:09] ✓ Retention cleanup complete
[2025-09-03 02:00:09] ========== Summary: 2 succeeded, 0 failed (8s) ==========
--- ## Error Handling | Scenario | Behaviour | |---|---| | DB unreachable | Log error, skip that DB, continue with others | | mysqldump fails mid-way | Delete partial temp file, log error, continue | | S3 unreachable / curl error | Log HTTP status + curl error, skip upload, clean temp file | | Missing required env var | Container exits immediately with clear message on startup | | Bucket doesn't exist | Auto-created via s3_create_bucket on first run | | Cron env var inheritance | Solved via /etc/environment export in entrypoint | --- ## Restore Procedure
bash
# Download via curl (signed GET request) or any S3-compatible tool
curl -o db1_2025-09-03_02-00-02.sql.gz \
  "http://<S3_ENDPOINT>/db-backups/backups/db1/db1_2025-09-03_02-00-02.sql.gz" \
  -H "Authorization: ..."

# Decompress and restore
gunzip < db1_2025-09-03_02-00-02.sql.gz | mysql \
  --host=<host> \
  --user=<user> \
  --password=<password> \
  db1
--- ## Future Enhancements (Out of Scope for v1) - **Notifications** — POST to a webhook (Slack, Telegram, ntfy.sh) on failure - **Encryption** — pipe through gpg before upload - **Multi-host** — accept a list of DB hosts - **PostgreSQL support** — swap mysqldump for pg_dump - **Healthcheck endpoint** — tiny HTTP server returning last backup status
# DB Backup Service — Automated MySQL/MariaDB Backups to MinIO

A lightweight Docker container that automatically backs up MySQL/MariaDB databases and uploads them to MinIO (or S3-compatible storage) using AWS Signature V4 authentication.

## Features

- ✅ **Automated Cron Scheduling** — Configurable backup frequency
- ✅ **Multi-Database Support** — Backup multiple databases in a single run
- ✅ **AWS Signature V4** — Secure uploads to MinIO/S3-compatible services
- ✅ **Compression** — Automatic gzip compression of SQL dumps
- ✅ **Retention Policies** — Automatic cleanup of old backups
- ✅ **Error Resilience** — Continues with next database on failure
- ✅ **Comprehensive Logging** — Detailed logs for troubleshooting

## Quick Start

### 1. Clone & Configure

```bash
cd /path/to/project
cp .env.example .env
```

Edit `.env` with your database and MinIO credentials:

```env
DB_HOST=mysql-server
DB_USER=root
DB_PASSWORD=your_password
DB_NAMES=database1,database2,database3

S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=strongpassword
S3_BUCKET=db-backups

CRON_SCHEDULE=0 2 * * *  # Daily at 2 AM
RETENTION_DAYS=30         # Keep 30 days of backups
```

### 2. Build & Run

**Using Docker Compose:**

```bash
docker-compose up -d
```

**Using Docker directly:**

```bash
docker build -t db-backup:1.0.0 .
docker run -d \
  --name db-backup \
  --restart unless-stopped \
  --env-file .env \
  -v ./logs:/var/log \
  db-backup:1.0.0
```

### 3. Verify

```bash
# Check container is running
docker ps | grep db-backup

# View logs
docker logs db-backup
tail -f ./logs/backup.log
```

## Configuration

All settings are controlled via environment variables (see `.env.example`):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_HOST` | ✅ | — | MySQL host (container name or IP) |
| `DB_PORT` | ❌ | 3306 | MySQL port |
| `DB_USER` | ✅ | — | MySQL username |
| `DB_PASSWORD` | ✅ | — | MySQL password |
| `DB_NAMES` | ✅ | — | Comma-separated database names |
| `S3_ENDPOINT` | ✅ | — | MinIO endpoint (e.g., `http://minio:9000`) |
| `S3_ACCESS_KEY` | ✅ | — | MinIO access key |
| `S3_SECRET_KEY` | ✅ | — | MinIO secret key |
| `S3_BUCKET` | ✅ | — | Target bucket name |
| `S3_PATH_PREFIX` | ❌ | `backups` | Folder prefix inside bucket |
| `S3_REGION` | ❌ | `us-east-1` | AWS region (MinIO ignores this) |
| `CRON_SCHEDULE` | ✅ | `0 2 * * *` | Cron expression (5-field format) |
| `RETENTION_DAYS` | ❌ | 30 | Delete backups older than N days (0 = keep forever) |
| `BACKUP_TIMEOUT` | ❌ | 3600 | Max seconds for mysqldump (per database) |

### Cron Schedule Examples

```
0 2 * * *       # Every day at 2:00 AM
0 */6 * * *     # Every 6 hours
30 3 * * 0      # Every Sunday at 3:30 AM
*/30 * * * *    # Every 30 minutes
0 1 1 * *       # First day of every month at 1:00 AM
```

## Backup File Structure

Backups are organized by database and timestamp:

```
S3_BUCKET/
└── S3_PATH_PREFIX/
    ├── database1/
    │   ├── database1_2025-09-03_02-00-00.sql.gz
    │   ├── database1_2025-09-04_02-00-00.sql.gz
    │   └── database1_2025-09-05_02-00-00.sql.gz
    ├── database2/
    │   └── database2_2025-09-05_02-00-00.sql.gz
    └── database3/
        └── database3_2025-09-05_02-00-00.sql.gz
```

## Restore Procedure

### Download from MinIO

```bash
# Using AWS CLI
aws s3 cp s3://db-backups/backups/database1/database1_2025-09-05_02-00-00.sql.gz . \
  --endpoint-url http://minio:9000 \
  --use-path-style-for-s3-uri
```

### Restore to Database

```bash
gunzip < database1_2025-09-05_02-00-00.sql.gz | mysql \
  -h mysql-host \
  -u root \
  -p database1
```

Or in one command:

```bash
aws s3 cp s3://db-backups/backups/database1/database1_2025-09-05_02-00-00.sql.gz - \
  --endpoint-url http://minio:9000 \
  --use-path-style-for-s3-uri | gunzip | mysql -h mysql-host -u root -p database1
```

## Logs

Logs are written to `/var/log/backup.log` inside the container.

**View live logs:**

```bash
docker exec db-backup tail -f /var/log/backup.log
```

**Log format:**

```
[2025-09-03 02:00:01] ========== Backup Run Started ==========
[2025-09-03 02:00:01] Run ID: 20250903_020001
[2025-09-03 02:00:02] Ensuring bucket exists...
[2025-09-03 02:00:02] ✓ Bucket ready
[2025-09-03 02:00:02] Processing database: database1
[2025-09-03 02:00:04] ✓ Dump complete: database1_2025-09-03_02-00-02.sql.gz (4.2 MB)
[2025-09-03 02:00:05] ✓ Uploaded: backups/database1/database1_2025-09-03_02-00-02.sql.gz
[2025-09-03 02:00:09] ========== Summary: 1 succeeded, 0 failed (8s) ==========
```

## Troubleshooting

### Container fails to start

**Check logs:**

```bash
docker logs db-backup
```

**Common issues:**

- Missing environment variables — ensure all required vars in `.env`
- Database unreachable — verify `DB_HOST`, `DB_PORT`, credentials
- MinIO unreachable — verify `S3_ENDPOINT`, bucket access

### Backup fails but container keeps running

Check the backup logs:

```bash
docker exec db-backup cat /var/log/backup.log
```

The container will retry at the next scheduled time.

### Permission denied on log volume

```bash
chmod 755 ./logs
```

## Docker Images & Publishing

### Build locally:

```bash
docker build -t db-backup:1.0.0 .
```

### Push to registry:

```bash
docker tag db-backup:1.0.0 registry.example.com/db-backup:1.0.0
docker push registry.example.com/db-backup:1.0.0
```

## Implementation Details

### Core Components

- **Dockerfile** — Debian-based, includes `mysql-client`, `curl`, `cron`, `openssl`
- **s3.sh** — Reusable S3 API functions (PUT, DELETE, LIST) with AWS Signature V4
- **backup.sh** — Main backup logic: dumping, compressing, uploading
- **entrypoint.sh** — Initialization, validation, cron setup
- **docker-compose.yml** — Container orchestration template

### mysqldump Flags

```bash
mysqldump \
  --single-transaction    # Consistent snapshot without table locks (InnoDB)
  --routines              # Include stored procedures & functions
  --triggers              # Include triggers
  --no-tablespaces        # Avoid permission errors on managed databases
```

### Signature V4 Authentication

Backups are uploaded using AWS Signature V4 with these steps:

1. Build canonical request with headers, method, path, query
2. Create string to sign with request hash and timestamp
3. Derive signing key using HMAC chain (date → region → service → signing)
4. Compute HMAC-SHA256 signature
5. Add `Authorization` header to curl request

## Environment Setup for Coolify

If deploying via **Coolify**, set these environment variables in your deployment service:

```
DB_HOST=your-mysql-service
DB_USER=root
DB_PASSWORD=***
DB_NAMES=database1,database2
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=***
S3_SECRET_KEY=***
S3_BUCKET=db-backups
CRON_SCHEDULE=0 2 * * *
RETENTION_DAYS=30
```

Coolify will handle the TLS reverse proxy — the container connects to MinIO via plain HTTP.

## Future Enhancements

- Webhook notifications (Slack, Telegram, ntfy.sh)
- Built-in encryption (GPG)
- PostgreSQL support
- Multi-host database backups
- Health check endpoint

## License

MIT

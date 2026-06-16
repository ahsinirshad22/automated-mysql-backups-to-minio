#!/usr/bin/env bash
set -euo pipefail

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "Error: Docker is not running. Please start Docker Desktop and try again."
    exit 1
fi

REGISTRY="harbor.ahsinirshad.com"
IMAGE_NAME="automated-backups/automated-mysql-backups-to-minio"
TAG="${1:-1.0.0}"

FULL_IMAGE="$REGISTRY/$IMAGE_NAME:$TAG"

echo "==> Building $FULL_IMAGE"
docker build --platform linux/amd64 -t "$FULL_IMAGE" .

echo "==> Pushing $FULL_IMAGE"
docker push "$FULL_IMAGE"

echo ""
echo "Done! Image available at:"
echo "  $FULL_IMAGE"

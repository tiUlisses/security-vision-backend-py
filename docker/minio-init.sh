#!/bin/sh
set -eu

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"

if [ -n "${MINIO_PUBLIC_BUCKETS:-}" ]; then
  for bucket in $MINIO_PUBLIC_BUCKETS; do
    mc mb --ignore-existing "local/$bucket"
    mc anonymous set public "local/$bucket"
  done
fi

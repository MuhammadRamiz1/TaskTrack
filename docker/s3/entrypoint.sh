#!/bin/sh
# Local S3-compatible object store (SeaweedFS). MinIO no longer publishes public
# container images, so SeaweedFS stands in for it in development. The application
# only speaks the S3 API (django-storages + boto3), so production can use AWS S3,
# MinIO, R2 or any S3-compatible service without code changes.
#
# Writes the S3 identity file from env, starts the server, then creates the private
# bucket once the S3 gateway answers.
set -eu

mkdir -p /etc/seaweedfs
cat > /etc/seaweedfs/s3.json <<EOF
{
  "identities": [
    {
      "name": "tasktrack",
      "credentials": [{"accessKey": "${S3_ACCESS_KEY}", "secretKey": "${S3_SECRET_KEY}"}],
      "actions": ["Admin", "Read", "Write", "List", "Tagging"]
    }
  ]
}
EOF

weed server -dir=/data -ip.bind=0.0.0.0 -volume.max=0 \
  -s3 -s3.port=8333 -s3.config=/etc/seaweedfs/s3.json \
  -s3.allowedOrigins="${WEB_ORIGIN}" &
SERVER_PID=$!

until wget -q -O /dev/null "http://127.0.0.1:8333/healthz" 2>/dev/null; do sleep 1; done
echo "s3.bucket.create -name ${S3_BUCKET}" | weed shell -master=127.0.0.1:9333 >/dev/null 2>&1 || true
echo "Bucket ${S3_BUCKET} ready."
touch /tmp/ready

wait "$SERVER_PID"

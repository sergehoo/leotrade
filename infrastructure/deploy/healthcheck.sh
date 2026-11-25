#!/bin/sh
set -e

curl -fsS http://127.0.0.1:8000/health/live/ >/dev/null
curl -fsS http://127.0.0.1:8000/health/ready/ >/dev/null

echo "ok"
#!/usr/bin/env bash
set -euo pipefail

python datanode.py 6001 &
python datanode.py 6002 &
python datanode.py 6003 &

exec gunicorn --bind "0.0.0.0:${PORT:-10000}" --workers 1 --threads 8 --timeout 120 namenode:app

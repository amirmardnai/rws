#!/bin/sh
set -e

export PORT=${PORT:-8000}
export ADMIN_PATH=${ADMIN_PATH:-panel}
export XHTTP_PATH=${XHTTP_PATH:-/api/v1/telemetry}
export WS_PATH=${WS_PATH:-/api/v1/live}
export GRPC_SERVICE=${GRPC_SERVICE:-api.cluster.v1}
export HU_PATH=${HU_PATH:-/api/v1/stream}

# Ensure temporary directories for Nginx exist with correct permissions
mkdir -p /tmp/client_temp /tmp/proxy_temp /tmp/fastcgi_temp /tmp/uwsgi_temp /tmp/scgi_temp

# Copy template nginx.conf and clear any default Debian package configs
cp /app/nginx.conf /etc/nginx/nginx.conf
rm -rf /etc/nginx/sites-enabled/* /etc/nginx/conf.d/* 2>/dev/null || true

# Substitute configuration placeholders in nginx.conf
sed -i "s|PORT_PLACEHOLDER|$PORT|g" /etc/nginx/nginx.conf
sed -i "s|XHTTP_PATH_PLACEHOLDER|$XHTTP_PATH|g" /etc/nginx/nginx.conf
sed -i "s|WS_PATH_PLACEHOLDER|$WS_PATH|g" /etc/nginx/nginx.conf
sed -i "s|GRPC_SERVICE_PLACEHOLDER|$GRPC_SERVICE|g" /etc/nginx/nginx.conf
sed -i "s|HU_PATH_PLACEHOLDER|$HU_PATH|g" /etc/nginx/nginx.conf
sed -i "s|SECRET_PATH_PLACEHOLDER|$ADMIN_PATH|g" /etc/nginx/nginx.conf

# Verify Nginx configuration syntax before starting
nginx -t

# File descriptors limit
ulimit -n 65535 2>/dev/null || true

# High-Performance Kernel & Network Tuning (BBR + Low Latency Sockets)
sysctl -w net.core.somaxconn=65535 >/dev/null 2>&1 || true
sysctl -w net.ipv4.tcp_max_syn_backlog=65535 >/dev/null 2>&1 || true
sysctl -w net.ipv4.tcp_fastopen=3 >/dev/null 2>&1 || true
sysctl -w net.ipv4.tcp_congestion_control=bbr >/dev/null 2>&1 || true
sysctl -w net.core.default_qdisc=fq >/dev/null 2>&1 || true
sysctl -w net.ipv4.tcp_rmem="4096 262144 16777216" >/dev/null 2>&1 || true
sysctl -w net.ipv4.tcp_wmem="4096 262144 16777216" >/dev/null 2>&1 || true
sysctl -w net.ipv4.tcp_slow_start_after_idle=0 >/dev/null 2>&1 || true

echo "Starting Nginx ingress on port $PORT..."
nginx

echo "Starting RWS Ingress Orchestrator..."
exec python3 -O /app/panel.py
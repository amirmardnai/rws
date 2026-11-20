# RWS - High-Performance Real-Time Web Stream & Ingress Engine

[![Deployment Status](https://img.shields.io/badge/status-active-success.svg)](https://railway.app)
[![Engine](https://img.shields.io/badge/engine-rws--core%20v2.4-blue.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

**RWS (Real-time Web Stream)** is an ultra-lightweight (<18MB RAM), high-concurrency event ingestion gateway and stream multiplexer designed for cloud PaaS environments (Railway, Docker, Kubernetes).

It combines an asynchronous Python orchestration controller with an optimized Nginx reverse proxy to deliver sub-millisecond edge routing, zero-logging telemetry pipelines, and multiplexed stream channels over HTTP/2, WebSocket, and gRPC.

---

## Architecture Overview

```
                      +-----------------------------+
                      |   Cloud Ingress / CDN Edge  |
                      +--------------+--------------+
                                     |
                      +--------------v--------------+
                      |   Nginx Ingress (Port 8000) |
                      |    (0-RTT, BBR Congestion)  |
                      +--+-----------+-----------+--+
                         |           |           |
       +-----------------+           |           +-----------------+
       |                             |                             |
+------v-------+             +-------v-------+             +-------v-------+
| Stream Ch 1  |             |  Stream Ch 2  |             | Stream Ch 3   |
| (Multiplexed)|             |  (WebSocket)  |             | (gRPC Engine) |
+------+-------+             +-------+-------+             +-------+-------+
       |                             |                             |
       +-----------------+           |           +-----------------+
                         |           |           |
                      +--v-----------v-----------v--+
                      |      RWS Ingress Core       |
                      |    (Non-blocking I/O)       |
                      +-----------------------------+
```

### Key Features

- **Micro-Memory Footprint:** Operates under 18MB RAM under sustained connection loads.
- **Multiplexed Transports:** Native support for XHTTP stream chunks, persistent WebSockets, and low-latency gRPC channels.
- **Kernel-Level Optimization:** Built-in sysctl tuning for BBR congestion control, high TCP syn backlogs, and non-blocking I/O.
- **Zero-Disk Logging:** Complete in-memory stream routing to prevent disk I/O bottlenecks and protect privacy.
- **Integrated Healthcheck:** Native `/health` endpoints compatible with PaaS automated deployment monitors.

---

## Configuration Variables

Configure these environment variables in your deployment dashboard or `.env` file:

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Ingress listening port (dynamically assigned by PaaS) |
| `ADMIN_PASSWORD` | `8282` | Authentication key for administrative portal and metrics export |
| `ADMIN_PATH` | `panel` | Secret path prefix for administrative endpoints |
| `UUID` | `90cd4a77-141a-43c9-991b-08263cfe9c10` | Unique cluster identification key |
| `PUBLIC_HOST` | `your-app.up.railway.app` | Public canonical hostname of your service |
| `XHTTP_PATH` | `/api/v1/telemetry` | Multiplexed stream transport endpoint |
| `WS_PATH` | `/api/v1/live` | Persistent WebSocket streaming endpoint |
| `GRPC_SERVICE` | `api.cluster.v1` | gRPC service routing identifier |
| `HU_PATH` | `/api/v1/stream` | Stream fallback endpoint |
| `CLEAN_IPS` | `104.17.70.206,172.64.154.211` | Ingress edge routing addresses |

---

## Deployment on Railway

1. Click **New Project** -> **Deploy from GitHub repo**.
2. Select repository `rws`.
3. In **Variables**, switch to **Raw Editor** and paste your environment variables.
4. Deploy! Railway will automatically detect the `Dockerfile` and launch the service.

---

## License

MIT License. Engineered for maximum throughput and reliability.

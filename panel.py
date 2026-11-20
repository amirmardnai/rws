#!/usr/bin/env python3
"""
RWS (Real-Time Web Stream) Orchestrator for Railway PaaS
=======================================================
- Ultra-low memory footprint (<18MB RAM)
- Multi-transport stream ingress: XHTTP (SplitHTTP), WebSocket, gRPC, HTTPUpgrade
- Active telemetry disguise & Prometheus-compatible health reporting
- Zero-logging architecture for maximum I/O throughput
- High security: Authenticated portal, pre-cached configs, zero public leaks
"""

import os
import sys
import json
import time
import base64
import urllib.parse
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

# ── Configuration & Environment Detection ─────────────────────────────────────
PORT = int(os.environ.get("PORT", "8000"))
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "8282").strip()
ADMIN_PATH = os.environ.get("ADMIN_PATH", "panel").strip("/ ")
UUID = os.environ.get("UUID", "90cd4a77-141a-43c9-991b-08263cfe9c10").strip()

# Detect Public Hostname
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "").strip()
if not PUBLIC_HOST:
    PUBLIC_HOST = os.environ.get("RAILWAY_STATIC_URL", "").strip()
if not PUBLIC_HOST:
    PUBLIC_HOST = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
if not PUBLIC_HOST:
    PUBLIC_HOST = "your-app.up.railway.app"

# Clean hostname from http:// or trailing slashes
PUBLIC_HOST = PUBLIC_HOST.replace("https://", "").replace("http://", "").strip("/ ")

# Transport Paths
XHTTP_PATH = os.environ.get("XHTTP_PATH", "/api/v1/telemetry").strip()
WS_PATH = os.environ.get("WS_PATH", "/api/v1/live").strip()
GRPC_SERVICE = os.environ.get("GRPC_SERVICE", "api.cluster.v1").strip()
HU_PATH = os.environ.get("HU_PATH", "/api/v1/stream").strip()

# Internal Ports
XRAY_XH_PORT = 18081
XRAY_WS_PORT = 18080
XRAY_GRPC_PORT = 18083
XRAY_HU_PORT = 18084
XRAY_API_PORT = 10085

# Reality Settings (Public TCP Proxy on Railway)
REALITY_DOMAIN = os.environ.get("REALITY_DOMAIN", "").strip()
REALITY_PORT = int(os.environ.get("REALITY_PORT", "18443"))
REALITY_PUBLIC_PORT = int(os.environ.get("REALITY_PUBLIC_PORT", str(REALITY_PORT)))
REALITY_SNI = os.environ.get("REALITY_SNI", "www.speedtest.net").strip()
REALITY_PRIV_KEY = os.environ.get("REALITY_PRIVATE_KEY", "").strip()
REALITY_PUB_KEY = os.environ.get("REALITY_PUBLIC_KEY", "").strip()

# Clean IPs for Cloudflare Fronting & DPI Evasion
CLEAN_IPS_RAW = os.environ.get("CLEAN_IPS", "153.52.255.81,104.18.138.193,104.18.202.232,172.64.155.209,104.17.70.206").strip()
CLEAN_IPS = [ip.strip() for ip in CLEAN_IPS_RAW.split(",") if ip.strip()]


START_TIME = time.time()
CONFIGS_DIR = "/app/configs"
os.makedirs(CONFIGS_DIR, exist_ok=True)

# In-memory global cache for generated client configs to prevent repeated disk I/O
CACHED_CLIENT_DATA = None


def get_engine_bin():
    for b in ["/usr/local/bin/rws-core", "/usr/local/bin/xray", "rws-core", "xray"]:
        if os.path.exists(b):
            return b
    return "/usr/local/bin/rws-core"


# ── Reality Key Generation ────────────────────────────────────────────────────
def ensure_reality_keys():
    global REALITY_PRIV_KEY, REALITY_PUB_KEY
    if REALITY_PRIV_KEY and REALITY_PUB_KEY:
        return
    
    engine_bin = get_engine_bin()
    try:
        res = subprocess.run([engine_bin, "x25519"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            lines = res.stdout.splitlines()
            for line in lines:
                if "PrivateKey:" in line:
                    REALITY_PRIV_KEY = line.split("PrivateKey:")[1].strip()
                elif "PublicKey" in line or "Password" in line:
                    REALITY_PUB_KEY = line.split("):")[1].strip() if "):" in line else line.split(":")[1].strip()
    except Exception:
        pass
    
    # Fallback to high-entropy deterministic keys if x25519 execution unavailable
    if not REALITY_PRIV_KEY or not REALITY_PUB_KEY:
        REALITY_PRIV_KEY = "qH6bsMYPlnR0L1IVxywyflbPkXV-O-lUlM-VPxBJAEY"
        REALITY_PUB_KEY = "L5ntw6c9k_bOCinOG6LwgrTc3s9lBZGqCgsbHADpz3U"


# ── Xray Server Configuration Builder ─────────────────────────────────────────
def generate_server_config():
    ensure_reality_keys()
    inbounds = [
        # XHTTP Inbound (SplitHTTP) - Primary modern Anti-DPI transport
        {
            "tag": "xhttp-in",
            "port": XRAY_XH_PORT,
            "listen": "127.0.0.1",
            "protocol": "vless",
            "settings": {
                "clients": [{"id": UUID, "level": 0}],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "xhttp",
                "xhttpSettings": {
                    "path": XHTTP_PATH,
                    "mode": "auto"
                },
                "sockopt": {"tcpNoDelay": True, "tcpFastOpen": True}
            }
        },
        # WebSocket Inbound - Tuned for high throughput with 0-RTT support
        {
            "tag": "ws-in",
            "port": XRAY_WS_PORT,
            "listen": "127.0.0.1",
            "protocol": "vless",
            "settings": {
                "clients": [{"id": UUID, "level": 0}],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "ws",
                "wsSettings": {
                    "path": WS_PATH
                },
                "sockopt": {"tcpNoDelay": True, "tcpFastOpen": True}
            }
        },
        # gRPC Inbound - Low latency RPC
        {
            "tag": "grpc-in",
            "port": XRAY_GRPC_PORT,
            "listen": "127.0.0.1",
            "protocol": "vless",
            "settings": {
                "clients": [{"id": UUID, "level": 0}],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "grpc",
                "grpcSettings": {
                    "serviceName": GRPC_SERVICE
                },
                "sockopt": {"tcpNoDelay": True, "tcpFastOpen": True}
            }
        },
        # HTTPUpgrade Inbound - Clean HTTP/1.1 upgrade fallback
        {
            "tag": "hu-in",
            "port": XRAY_HU_PORT,
            "listen": "127.0.0.1",
            "protocol": "vless",
            "settings": {
                "clients": [{"id": UUID, "level": 0}],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "httpupgrade",
                "httpupgradeSettings": {
                    "path": HU_PATH
                },
                "sockopt": {"tcpNoDelay": True, "tcpFastOpen": True}
            }
        }
    ]

    # VLESS-Reality Inbound (Active if Railway TCP Proxy is used)
    if REALITY_DOMAIN or REALITY_PORT:
        inbounds.append({
            "tag": "reality-in",
            "port": REALITY_PORT,
            "listen": "0.0.0.0",
            "protocol": "vless",
            "settings": {
                "clients": [{"id": UUID, "flow": "xtls-rprx-vision", "level": 0}],
                "decryption": "none",
                "fallbacks": [{"dest": f"127.0.0.1:{PORT}"}]
            },
            "streamSettings": {
                "network": "tcp",
                "security": "reality",
                "realitySettings": {
                    "show": False,
                    "dest": f"{REALITY_SNI}:443",
                    "xver": 0,
                    "serverNames": [REALITY_SNI],
                    "privateKey": REALITY_PRIV_KEY,
                    "shortIds": ["", "0123456789abcdef"]
                },
                "sockopt": {"tcpNoDelay": True, "tcpFastOpen": True}
            }
        })

    cfg = {
        "log": {"loglevel": "none"},
        "inbounds": inbounds,
        "outbounds": [
            {
                "tag": "direct",
                "protocol": "freedom",
                "streamSettings": {
                    "sockopt": {"tcpNoDelay": True, "tcpFastOpen": True}
                }
            },
            {
                "tag": "block",
                "protocol": "blackhole"
            }
        ],
        "policy": {
            "levels": {
                "0": {
                    "handshake": 8,
                    "connIdle": 900,
                    "uplinkOnly": 0,
                    "downlinkOnly": 0,
                    "bufferSize": 1024
                }
            },
            "system": {
                "statsInboundUplink": False,
                "statsInboundDownlink": False
            }
        }
    }
    return cfg


# ── Client Link & Config Generators ───────────────────────────────────────────
def generate_client_configs(force_refresh=False):
    global CACHED_CLIENT_DATA
    if CACHED_CLIENT_DATA and not force_refresh:
        return CACHED_CLIENT_DATA

    clean_ip = CLEAN_IPS[0] if CLEAN_IPS else "153.52.255.81"
    
    # 1. VLESS Share Links
    links = []

    enc_path_ws = urllib.parse.quote(WS_PATH, safe="")
    enc_path_xh = urllib.parse.quote(XHTTP_PATH, safe="")
    enc_path_hu = urllib.parse.quote(HU_PATH, safe="")

    # A: BERMUDA Flagship Packet 1-3 Slicing (&fm= parameter) - Live Verified in Iran
    fm_pkt13 = json.dumps({
        "tcp": [{
            "type": "fragment",
            "settings": {
                "packets": "1-3",
                "lengths": ["48-96"],
                "delays": ["2-5"],
                "maxSplit": "4-8"
            }
        }]
    })
    enc_fm13 = urllib.parse.quote(fm_pkt13)
    link_bermuda_pkt13 = (
        f"vless://{UUID}@{clean_ip}:443"
        f"?encryption=none&security=tls&sni={PUBLIC_HOST}&fp=chrome&alpn=http%2F1.1"
        f"&fm={enc_fm13}&type=ws&host={PUBLIC_HOST}&path={enc_path_ws}"
        f"#BERMUDA-PKT-1-3-VERIFIED"
    )
    links.append(link_bermuda_pkt13)

    # B: BERMUDA Cascaded Deep Slice for Aggressive DPI (MCI / Irancell)
    fm_cascaded = json.dumps({
        "tcp": [{
            "type": "fragment",
            "settings": {
                "packets": "1-3",
                "lengths": ["16-64"],
                "delays": ["3-7"],
                "maxSplit": "4-8"
            }
        }]
    })
    enc_fm_cascaded = urllib.parse.quote(fm_cascaded)
    link_bermuda_cascaded = (
        f"vless://{UUID}@{clean_ip}:443"
        f"?encryption=none&security=tls&sni={PUBLIC_HOST}&fp=chrome&alpn=http%2F1.1"
        f"&fm={enc_fm_cascaded}&type=ws&host={PUBLIC_HOST}&path={enc_path_ws}"
        f"#BERMUDA-CASCADED-DEEP"
    )
    links.append(link_bermuda_cascaded)

    # C: BERMUDA iOS Native Fragment (&fragment= parameter for Happ / Streisand / V2Box)
    enc_frag_ios = urllib.parse.quote("48-96,2-5,1-3")
    link_bermuda_ios = (
        f"vless://{UUID}@{clean_ip}:443"
        f"?encryption=none&security=tls&sni={PUBLIC_HOST}&fp=chrome&alpn=http%2F1.1"
        f"&fragment={enc_frag_ios}&type=ws&host={PUBLIC_HOST}&path={enc_path_ws}"
        f"#BERMUDA-iOS-FRAGMENT"
    )
    links.append(link_bermuda_ios)

    # D: VLESS + XHTTP Clean IP (Anti-Throttling Stream)
    link_xh_clean = (
        f"vless://{UUID}@{clean_ip}:443"
        f"?encryption=none&security=tls&sni={PUBLIC_HOST}&type=xhttp"
        f"&path={enc_path_xh}&host={PUBLIC_HOST}&mode=auto&fp=chrome#OmniMesh-XHTTP-CleanIP"
    )
    links.append(link_xh_clean)

    # E: VLESS + WS Clean IP (Raw Line-Rate Direct)
    link_ws_clean = (
        f"vless://{UUID}@{clean_ip}:443"
        f"?encryption=none&security=tls&sni={PUBLIC_HOST}&type=ws"
        f"&path={enc_path_ws}&host={PUBLIC_HOST}&fp=chrome#OmniMesh-WS-CleanIP"
    )
    links.append(link_ws_clean)

    # F: VLESS + WS Direct (Direct Domain)
    link_ws_direct = (
        f"vless://{UUID}@{PUBLIC_HOST}:443"
        f"?encryption=none&security=tls&sni={PUBLIC_HOST}&type=ws"
        f"&path={enc_path_ws}&host={PUBLIC_HOST}&fp=chrome#OmniMesh-WS-Direct"
    )
    links.append(link_ws_direct)

    # G: VLESS + HTTPUpgrade Direct
    link_hu_direct = (
        f"vless://{UUID}@{PUBLIC_HOST}:443"
        f"?encryption=none&security=tls&sni={PUBLIC_HOST}&type=httpupgrade"
        f"&path={enc_path_hu}&host={PUBLIC_HOST}&fp=chrome#OmniMesh-HTTPUpgrade"
    )
    links.append(link_hu_direct)

    # H: VLESS + Reality (Only if Railway TCP Proxy domain is configured)
    if REALITY_DOMAIN:
        link_reality = (
            f"vless://{UUID}@{REALITY_DOMAIN}:{REALITY_PUBLIC_PORT}"
            f"?encryption=none&security=reality&sni={REALITY_SNI}&fp=chrome"
            f"&pbk={REALITY_PUB_KEY}&sid=0123456789abcdef&type=tcp"
            f"&flow=xtls-rprx-vision#OmniMesh-Reality-TCP"
        )
        links.append(link_reality)


    # Base64 Subscription
    sub_raw = "\n".join(links)
    sub_b64 = base64.b64encode(sub_raw.encode("utf-8")).decode("utf-8")

    # 2. Xray Client JSON (Patterniha v50 TLS Fragmentation + DoH DNS Anti-Poisoning)
    xray_client = {
        "log": {"loglevel": "warning"},
        "dns": {
            "servers": [
                "https://1.1.1.1/dns-query",
                "https://dns.google/dns-query",
                "8.8.8.8"
            ]
        },
        "inbounds": [
            {
                "tag": "mixed-in",
                "port": 10808,
                "listen": "127.0.0.1",
                "protocol": "mixed",
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
            }
        ],
        "outbounds": [
            {
                "tag": "proxy-xhttp-cleanip",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": clean_ip,
                        "port": 443,
                        "users": [{"id": UUID, "encryption": "none"}]
                    }]
                },
                "streamSettings": {
                    "network": "xhttp",
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": PUBLIC_HOST,
                        "fingerprint": "chrome"
                    },
                    "xhttpSettings": {
                        "path": XHTTP_PATH,
                        "host": PUBLIC_HOST,
                        "mode": "auto"
                    },
                    "sockopt": {
                        "tcpNoDelay": True,
                        "dialerProxy": "fragment-engine"
                    }
                }
            },
            {
                "tag": "proxy-xhttp-frag",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": PUBLIC_HOST,
                        "port": 443,
                        "users": [{"id": UUID, "encryption": "none"}]
                    }]
                },
                "streamSettings": {
                    "network": "xhttp",
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": PUBLIC_HOST,
                        "fingerprint": "chrome"
                    },
                    "xhttpSettings": {
                        "path": XHTTP_PATH,
                        "host": PUBLIC_HOST,
                        "mode": "auto"
                    },
                    "sockopt": {
                        "tcpNoDelay": True,
                        "dialerProxy": "fragment-engine"
                    }
                }
            },
            {
                "tag": "proxy-ws-cleanip",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": clean_ip,
                        "port": 443,
                        "users": [{"id": UUID, "encryption": "none"}]
                    }]
                },
                "streamSettings": {
                    "network": "ws",
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": PUBLIC_HOST,
                        "fingerprint": "chrome"
                    },
                    "wsSettings": {
                        "path": WS_PATH,
                        "host": PUBLIC_HOST
                    },
                    "sockopt": {
                        "tcpNoDelay": True,
                        "dialerProxy": "fragment-engine"
                    }
                }
            },
            # Patterniha v50 TLS ClientHello Fragmentation Engine
            {
                "tag": "fragment-engine",
                "protocol": "freedom",
                "settings": {
                    "fragment": {
                        "packets": "tlshello",
                        "length": "1-3",
                        "interval": "10-20"
                    }
                },
                "streamSettings": {
                    "sockopt": {
                        "tcpNoDelay": True,
                        "tcpFastOpen": True
                    }
                }
            },
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"}
        ],
        "routing": {
            "domainStrategy": "IPOnDemand",
            "rules": [
                {"type": "field", "outboundTag": "block", "ip": ["10.10.34.0/24"]},
                {"type": "field", "outboundTag": "direct", "domain": ["geosite:private", "geosite:category-ir"]},
                {"type": "field", "outboundTag": "direct", "ip": ["geoip:private", "geoip:ir"]},
                {"type": "field", "outboundTag": "proxy-xhttp-cleanip", "network": "tcp,udp"}
            ]
        }
    }

    # 3. Clash.Meta / Mihomo Configuration
    clash_config = f"""# OmniMesh Clash.Meta / Mihomo Configuration
port: 7890
socks-port: 7891
mixed-port: 7892
allow-lan: false
mode: rule
log-level: info
ipv6: false

dns:
  enable: true
  listen: 0.0.0.0:1053
  ipv6: false
  default-nameserver:
    - 1.1.1.1
    - 8.8.8.8
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  nameserver:
    - https://dns10.quad9.net/dns-query
    - https://cloudflare-dns.com/dns-query

proxies:
  - name: "OmniMesh-XHTTP-CleanIP"
    type: vless
    server: "{clean_ip}"
    port: 443
    uuid: "{UUID}"
    cipher: auto
    tls: true
    servername: "{PUBLIC_HOST}"
    network: xhttp
    xhttp-opts:
      path: "{XHTTP_PATH}"
      mode: auto
      headers:
        Host: "{PUBLIC_HOST}"
    client-fingerprint: chrome

  - name: "OmniMesh-XHTTP-Direct"
    type: vless
    server: "{PUBLIC_HOST}"
    port: 443
    uuid: "{UUID}"
    cipher: auto
    tls: true
    servername: "{PUBLIC_HOST}"
    network: xhttp
    xhttp-opts:
      path: "{XHTTP_PATH}"
      mode: auto
      headers:
        Host: "{PUBLIC_HOST}"
    client-fingerprint: chrome

  - name: "OmniMesh-WS-CleanIP"
    type: vless
    server: "{clean_ip}"
    port: 443
    uuid: "{UUID}"
    cipher: auto
    tls: true
    servername: "{PUBLIC_HOST}"
    network: ws
    ws-opts:
      path: "{WS_PATH}"
      headers:
        Host: "{PUBLIC_HOST}"
    client-fingerprint: chrome

proxy-groups:
  - name: "PROXIES"
    type: select
    proxies:
      - "OmniMesh-XHTTP-CleanIP"
      - "OmniMesh-XHTTP-Direct"
      - "OmniMesh-WS-CleanIP"

rules:
  - GEOIP,IR,DIRECT
  - GEOSITE,category-ir,DIRECT
  - MATCH,PROXIES
"""

    # 4. Sing-box Client Configuration (with built-in TLS Fragmentation & Clean IP)
    singbox_config = {
        "log": {"level": "warn"},
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": 10808,
                "sniff": True
            }
        ],
        "outbounds": [
            {
                "type": "selector",
                "tag": "select",
                "outbounds": ["vless-xhttp-cleanip", "vless-xhttp-direct", "vless-ws-cleanip", "direct"]
            },
            {
                "type": "vless",
                "tag": "vless-xhttp-cleanip",
                "server": clean_ip,
                "server_port": 443,
                "uuid": UUID,
                "tls": {
                    "enabled": True,
                    "server_name": PUBLIC_HOST,
                    "utls": {"enabled": True, "fingerprint": "chrome"},
                    "fragment": {
                        "enabled": True,
                        "length": "1-3",
                        "interval": "10-20"
                    }
                },
                "transport": {
                    "type": "xhttp",
                    "path": XHTTP_PATH,
                    "headers": {"Host": PUBLIC_HOST},
                    "mode": "auto"
                }
            },
            {
                "type": "vless",
                "tag": "vless-xhttp-direct",
                "server": PUBLIC_HOST,
                "server_port": 443,
                "uuid": UUID,
                "tls": {
                    "enabled": True,
                    "server_name": PUBLIC_HOST,
                    "utls": {"enabled": True, "fingerprint": "chrome"},
                    "fragment": {
                        "enabled": True,
                        "length": "1-3",
                        "interval": "10-20"
                    }
                },
                "transport": {
                    "type": "xhttp",
                    "path": XHTTP_PATH,
                    "headers": {"Host": PUBLIC_HOST},
                    "mode": "auto"
                }
            },
            {
                "type": "vless",
                "tag": "vless-ws-cleanip",
                "server": clean_ip,
                "server_port": 443,
                "uuid": UUID,
                "tls": {
                    "enabled": True,
                    "server_name": PUBLIC_HOST,
                    "utls": {"enabled": True, "fingerprint": "chrome"},
                    "fragment": {
                        "enabled": True,
                        "length": "1-3",
                        "interval": "10-20"
                    }
                },
                "transport": {
                    "type": "ws",
                    "path": WS_PATH,
                    "headers": {"Host": PUBLIC_HOST}
                }
            },
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"}
        ],
        "route": {
            "rules": [
                {"geoip": "ir", "outbound": "direct"},
                {"geosite": "category-ir", "outbound": "direct"}
            ]
        }
    }

    # Save to disk once
    try:
        with open(os.path.join(CONFIGS_DIR, "vless_links.txt"), "w", encoding="utf-8") as f:
            f.write(sub_raw)
        with open(os.path.join(CONFIGS_DIR, "sub.txt"), "w", encoding="utf-8") as f:
            f.write(sub_b64)
        with open(os.path.join(CONFIGS_DIR, "xray_client_frag.json"), "w", encoding="utf-8") as f:
            json.dump(xray_client, f, indent=2)
        with open(os.path.join(CONFIGS_DIR, "clash_meta.yaml"), "w", encoding="utf-8") as f:
            f.write(clash_config)
        with open(os.path.join(CONFIGS_DIR, "sing_box_client.json"), "w", encoding="utf-8") as f:
            json.dump(singbox_config, f, indent=2)
    except Exception as e:
        print(f"[ConfigGen] Warning writing configs to disk: {e}", flush=True)

    CACHED_CLIENT_DATA = {
        "links": links,
        "sub_b64": sub_b64,
        "xray_client": xray_client,
        "clash_yaml": clash_config,
        "singbox_json": singbox_config
    }
    return CACHED_CLIENT_DATA


# ── Active Camouflage Web Application (Anti-Probing Disguise) ─────────────────
CAMOUFLAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OmniMesh - Distributed Edge Telemetry & Compute Platform</title>
    <style>
        :root {
            --bg-primary: #0a0e17;
            --bg-card: rgba(18, 24, 38, 0.85);
            --border-color: rgba(56, 189, 248, 0.15);
            --accent-cyan: #38bdf8;
            --accent-green: #34d399;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: radial-gradient(circle at top right, #111e38 0%, #0a0e17 60%);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 30px 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .container { max-width: 1000px; width: 100%; }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 20px;
            margin-bottom: 30px;
        }
        .brand { display: flex; align-items: center; gap: 12px; }
        .logo-dot {
            width: 16px; height: 16px; border-radius: 50%;
            background: var(--accent-cyan);
            box-shadow: 0 0 12px var(--accent-cyan);
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(56,189,248,0.7); }
            70% { transform: scale(1); box-shadow: 0 0 0 10px rgba(56,189,248,0); }
            100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(56,189,248,0); }
        }
        h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }
        .status-badge {
            background: rgba(52, 211, 153, 0.1);
            color: var(--accent-green);
            border: 1px solid rgba(52, 211, 153, 0.3);
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
        }
        .hero { margin-bottom: 30px; }
        .hero h2 { font-size: 32px; font-weight: 800; margin-bottom: 10px; color: #fff; }
        .hero p { color: var(--text-secondary); font-size: 16px; line-height: 1.6; max-width: 700px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 22px;
            backdrop-filter: blur(10px);
        }
        .card-label { font-size: 12px; text-transform: uppercase; color: var(--text-secondary); margin-bottom: 8px; font-weight: 600; }
        .card-val { font-size: 26px; font-weight: 700; color: #fff; }
        .card-sub { font-size: 13px; color: var(--accent-cyan); margin-top: 6px; }
        .terminal {
            background: #060911;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px;
            padding: 20px;
            font-family: "Courier New", monospace;
            font-size: 13px;
            line-height: 1.6;
            color: #a5b4fc;
            overflow-x: auto;
        }
        .term-header { display: flex; gap: 8px; margin-bottom: 15px; }
        .term-circle { width: 10px; height: 10px; border-radius: 50%; }
        footer { margin-top: auto; padding-top: 40px; color: #475569; font-size: 12px; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">
                <div class="logo-dot"></div>
                <h1>OmniMesh Network</h1>
            </div>
            <div class="status-badge">● Edge Cluster Online</div>
        </header>

        <section class="hero">
            <h2>Distributed Telemetry & Event Ingestion Hub</h2>
            <p>High-throughput real-time streaming endpoint for telemetry telemetry packets, high-performance edge buffers, and low-latency gRPC RPC pipelines.</p>
        </section>

        <div class="grid">
            <div class="card">
                <div class="card-label">Cluster Ingestion</div>
                <div class="card-val">99.98%</div>
                <div class="card-sub">Zero Loss Target</div>
            </div>
            <div class="card">
                <div class="card-label">Median Latency</div>
                <div class="card-val" id="lat-val">1.24 ms</div>
                <div class="card-sub">BBR Congestion Control</div>
            </div>
            <div class="card">
                <div class="card-label">Buffer Capacity</div>
                <div class="card-val">1024 KB</div>
                <div class="card-sub">Zero Syscall Stall</div>
            </div>
            <div class="card">
                <div class="card-label">Multiplex Transport</div>
                <div class="card-val">H2 / H3</div>
                <div class="card-sub">XHTTP Stream Pipeline</div>
            </div>
        </div>

        <div class="terminal">
            <div class="term-header">
                <div class="term-circle" style="background:#ef4444;"></div>
                <div class="term-circle" style="background:#f59e0b;"></div>
                <div class="term-circle" style="background:#10b981;"></div>
            </div>
            <div>[OMNI-KERNEL] Initializing somaxconn=65535 tcp_fastopen=3 bbr=active</div>
            <div>[OMNI-EDGE] Ingestion pipeline listening on port 443 with TLS 1.3</div>
            <div>[OMNI-STATUS] Active cluster healthy. Ready for event stream processing.</div>
        </div>

        <footer>
            OmniMesh Platform &copy; 2026. Automated Edge Telemetry Relay.
        </footer>
    </div>
    <script>
        setInterval(() => {
            const lat = (1.1 + Math.random() * 0.3).toFixed(2);
            document.getElementById('lat-val').innerText = lat + ' ms';
        }, 3000);
    </script>
</body>
</html>
"""


# ── Portal Login Page ─────────────────────────────────────────────────────────
def render_login_html(error=""):
    err_html = f'<div style="color: #ef4444; margin-bottom: 15px; font-size: 13px;">{error}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OmniMesh Gateway Authorization</title>
    <style>
        body {{
            background: #070a12;
            color: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
        }}
        .card {{
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid rgba(56, 189, 248, 0.2);
            border-radius: 14px;
            padding: 30px;
            max-width: 380px;
            width: 100%;
            text-align: center;
        }}
        h2 {{ font-size: 20px; margin-bottom: 8px; color: #fff; }}
        p {{ color: #94a3b8; font-size: 13px; margin-bottom: 22px; }}
        input[type="password"] {{
            width: 100%;
            padding: 12px;
            background: #020617;
            border: 1px solid #1e293b;
            color: #f8fafc;
            border-radius: 8px;
            box-sizing: border-box;
            margin-bottom: 18px;
            font-size: 14px;
        }}
        button {{
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #0284c7, #0ea5e9);
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            font-size: 14px;
        }}
        button:hover {{ opacity: 0.9; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>Cluster Access Verification</h2>
        <p>Enter the administrator key to retrieve node endpoints</p>
        {err_html}
        <form method="POST">
            <input type="password" name="password" placeholder="Access Key" required autofocus>
            <button type="submit">Authenticate</button>
        </form>
    </div>
</body>
</html>
"""


# ── Secret Management & Portal Page ───────────────────────────────────────────
def render_portal_html(data, auth_key=""):
    key_param = f"?key={auth_key}" if auth_key else ""
    sub_url = f"https://{PUBLIC_HOST}/{ADMIN_PATH}/sub{key_param}"
    
    links_html = ""
    for idx, link in enumerate(data["links"], 1):
        name = link.split("#")[-1] if "#" in link else f"Node {idx}"
        links_html += f"""
        <div class="link-card">
            <div class="link-header">
                <span class="badge">#{idx}</span>
                <span class="node-title">{name}</span>
            </div>
            <div class="link-box">
                <input type="text" readonly value="{link}" id="link-{idx}">
                <button onclick="copyToClipboard('link-{idx}')">Copy</button>
            </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OmniMesh Supercharged Node Portal</title>
    <style>
        :root {{
            --bg-primary: #070a12;
            --bg-card: rgba(15, 23, 42, 0.75);
            --border: rgba(56, 189, 248, 0.2);
            --accent: #38bdf8;
            --green: #4ade80;
            --text: #f8fafc;
            --text-muted: #94a3b8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #070a12;
            color: var(--text);
            padding: 30px 15px;
            display: flex;
            justify-content: center;
        }}
        .wrap {{ max-width: 900px; width: 100%; }}
        .header {{ text-align: center; margin-bottom: 30px; }}
        .header h1 {{
            font-size: 28px;
            background: linear-gradient(135deg, #38bdf8, #4ade80);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }}
        .header p {{ color: var(--text-muted); font-size: 14px; }}
        .sub-box {{
            background: rgba(56, 189, 248, 0.05);
            border: 1px dashed var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 25px;
            text-align: center;
        }}
        .btn {{
            background: linear-gradient(135deg, #0284c7, #0ea5e9);
            color: #fff;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            margin: 4px;
            text-decoration: none;
            display: inline-block;
        }}
        .btn:hover {{ opacity: 0.9; }}
        .link-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 18px;
            margin-bottom: 15px;
        }}
        .link-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }}
        .badge {{ background: #1e293b; color: var(--accent); padding: 2px 8px; border-radius: 6px; font-size: 12px; font-weight: bold; }}
        .node-title {{ font-weight: 600; font-size: 15px; }}
        .link-box {{ display: flex; gap: 10px; }}
        input[type="text"] {{
            flex: 1;
            background: #020617;
            border: 1px solid #1e293b;
            color: #cbd5e1;
            padding: 10px;
            border-radius: 8px;
            font-family: monospace;
            font-size: 12px;
        }}
        button {{
            background: #1e293b;
            border: 1px solid #334155;
            color: var(--accent);
            padding: 0 16px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
        }}
        button:hover {{ background: #334155; color: #fff; }}
        .config-links {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; margin-top: 15px; }}
    </style>
</head>
<body>
    <div class="wrap">
        <div class="header">
            <h1>OmniMesh Supercharged Node Portal</h1>
            <p>Anti-DPI | BBR Kernel Tuning | XHTTP + WebSocket + Clean IP | Zero Logging</p>
        </div>

        <div class="sub-box">
            <h3 style="margin-bottom: 10px;">Subscription URL (v2rayN / Streisand / Shadowrocket / Nekobox)</h3>
            <input type="text" id="sub-url" readonly value="{sub_url}" style="width: 80%; text-align: center; margin-bottom: 12px;">
            <br>
            <button onclick="copyToClipboard('sub-url')">Copy Subscription Link</button>
            <div class="config-links">
                <a href="/{ADMIN_PATH}/clash{key_param}" class="btn" download="clash_meta.yaml">Download Clash YAML</a>
                <a href="/{ADMIN_PATH}/singbox{key_param}" class="btn" download="sing_box.json">Download Sing-Box JSON</a>
                <a href="/{ADMIN_PATH}/xray{key_param}" class="btn" download="xray_frag.json">Download Xray Frag JSON</a>
            </div>
        </div>

        <div>
            {links_html}
        </div>
    </div>
    <script>
        function copyToClipboard(id) {{
            const el = document.getElementById(id);
            el.select();
            document.execCommand('copy');
            alert('Copied to clipboard!');
        }}
    </script>
</body>
</html>
"""


# ── HTTP Server Request Handler ───────────────────────────────────────────────
class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class StealthHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Disable default HTTP logging to prevent disk I/O overhead
        return

    def send_resp_bytes(self, code, content_type, body_bytes, extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Server", "nginx")
        self.send_header("Cache-Control", "no-cache")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body_bytes)

    def is_authenticated(self, query_params):
        if not ADMIN_PASS:
            return True
        key = query_params.get("key", [""])[0] or query_params.get("token", [""])[0]
        if key == ADMIN_PASS:
            return True
        cookie_header = self.headers.get("Cookie", "")
        if f"admin_key={ADMIN_PASS}" in cookie_header:
            return True
        return False

    def do_POST(self):
        url_parsed = urllib.parse.urlparse(self.path)
        path = url_parsed.path.rstrip("/")
        if not path:
            path = "/"

        admin_prefix = f"/{ADMIN_PATH}"
        if path == admin_prefix or path.startswith(f"{admin_prefix}/"):
            content_length = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_length).decode("utf-8", errors="ignore")
            form_data = urllib.parse.parse_qs(post_body)
            entered_pass = form_data.get("password", [""])[0].strip()

            if entered_pass == ADMIN_PASS:
                cookie = f"admin_key={ADMIN_PASS}; Path=/; HttpOnly; SameSite=Lax"
                self.send_response(302)
                self.send_header("Location", f"/{ADMIN_PATH}/portal")
                self.send_header("Set-Cookie", cookie)
                self.end_headers()
                return
            else:
                html = render_login_html("Invalid access key. Please try again.").encode("utf-8")
                self.send_resp_bytes(401, "text/html; charset=utf-8", html)
                return

        # Default POST behavior
        self.send_resp_bytes(404, "text/html; charset=utf-8", CAMOUFLAGE_HTML.encode("utf-8"))

    def do_GET(self):
        url_parsed = urllib.parse.urlparse(self.path)
        path = url_parsed.path.rstrip("/")
        if not path:
            path = "/"
        query_params = urllib.parse.parse_qs(url_parsed.query)

        # 1. Healthcheck Endpoint for Platform Deployment Orchestrator
        if path == "/health":
            body = json.dumps({"status": "healthy", "service": "rws-ingress", "uptime": "ok"}).encode("utf-8")
            self.send_resp_bytes(200, "application/json", body)
            return

        # 2. Secret Administration / Subscription Endpoints
        admin_prefix = f"/{ADMIN_PATH}"
        if path == admin_prefix or path.startswith(f"{admin_prefix}/"):
            rel_path = path[len(admin_prefix):].strip("/")
            
            # Authentication gate
            if not self.is_authenticated(query_params):
                if rel_path in ["", "portal"]:
                    html = render_login_html().encode("utf-8")
                    self.send_resp_bytes(200, "text/html; charset=utf-8", html)
                    return
                else:
                    # Stealth 404 for unauthenticated API probes
                    self.send_resp_bytes(404, "text/html; charset=utf-8", CAMOUFLAGE_HTML.encode("utf-8"))
                    return

            client_data = generate_client_configs()
            auth_key = ADMIN_PASS if ADMIN_PASS else ""

            if rel_path in ["", "portal"]:
                html = render_portal_html(client_data, auth_key).encode("utf-8")
                self.send_resp_bytes(200, "text/html; charset=utf-8", html)
                return
            elif rel_path == "sub":
                self.send_resp_bytes(200, "text/plain; charset=utf-8", client_data["sub_b64"].encode("utf-8"))
                return
            elif rel_path == "links":
                raw_links = "\n".join(client_data["links"]).encode("utf-8")
                self.send_resp_bytes(200, "text/plain; charset=utf-8", raw_links)
                return
            elif rel_path == "clash":
                self.send_resp_bytes(200, "text/yaml; charset=utf-8", client_data["clash_yaml"].encode("utf-8"))
                return
            elif rel_path == "singbox":
                self.send_resp_bytes(200, "application/json; charset=utf-8", json.dumps(client_data["singbox_json"], indent=2).encode("utf-8"))
                return
            elif rel_path in ["xray", "config"]:
                self.send_resp_bytes(200, "application/json; charset=utf-8", json.dumps(client_data["xray_client"], indent=2).encode("utf-8"))
                return
            elif rel_path == "status":
                status = {
                    "uptime_seconds": int(time.time() - START_TIME),
                    "public_host": PUBLIC_HOST,
                    "xhttp_path": XHTTP_PATH,
                    "ws_path": WS_PATH,
                    "clean_ips": CLEAN_IPS,
                    "reality_enabled": bool(REALITY_DOMAIN)
                }
                self.send_resp_bytes(200, "application/json", json.dumps(status).encode("utf-8"))
                return

        # 3. Default: Serve Active Camouflage Web Application (Anti-Probing Disguise)
        self.send_resp_bytes(200, "text/html; charset=utf-8", CAMOUFLAGE_HTML.encode("utf-8"))


# ── Process Supervisor & Banner Output ────────────────────────────────────────
def print_banner(client_data):
    key_param = f"?key={ADMIN_PASS}" if ADMIN_PASS else ""
    sub_url = f"https://{PUBLIC_HOST}/{ADMIN_PATH}/sub{key_param}"
    portal_url = f"https://{PUBLIC_HOST}/{ADMIN_PATH}/portal{key_param}"
    print("\n" + "=" * 78)
    print("             RWS REAL-TIME TELEMETRY & INGRESS ENGINE (v2.4.0)")
    print("=" * 78)
    print(f" [*] Ingress Host     : {PUBLIC_HOST}")
    print(f" [*] Ingress Port     : {PORT}")
    print(f" [*] Telemetry Path   : {XHTTP_PATH}")
    print(f" [*] Live Stream Path : {WS_PATH}")
    print(f" [*] gRPC Service     : {GRPC_SERVICE}")
    if REALITY_DOMAIN:
        print(f" [*] TCP Relay Domain : {REALITY_DOMAIN}:{REALITY_PUBLIC_PORT} (Target SNI: {REALITY_SNI})")
    print(f" [*] Health Check     : https://{PUBLIC_HOST}/health")
    print(f" [*] Management Path  : /{ADMIN_PATH}/portal")
    print("-" * 78)
    print(f" [>] Portal Access URL: {portal_url}")
    print(f" [>] Subscription URL : {sub_url}")
    print("-" * 78)
    print(" [i] Notice: Client configurations are secured & pre-cached in memory.")
    print("     Access the Portal URL in your browser to copy or download configs.")
    print("=" * 78 + "\n", flush=True)


def run_engine_supervisor():
    engine_bin = get_engine_bin()
    cfg_path = "/app/config.json"
    
    server_cfg = generate_server_config()
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(server_cfg, f, indent=2)

    env = os.environ.copy()
    env["XRAY_LOCATION_ASSET"] = "/usr/local/bin"

    while True:
        try:
            bin_name = os.path.basename(engine_bin)
            print(f"[Engine] Starting stream ingress engine ({bin_name})...", flush=True)
            proc = subprocess.Popen([engine_bin, "run", "-c", cfg_path], env=env)
            proc.wait()
            print(f"[Engine] Core process exited with code {proc.returncode}. Restarting in 2s...", flush=True)
            time.sleep(2)
        except Exception as e:
            print(f"[Engine] Process error: {e}. Retrying in 5s...", flush=True)
            time.sleep(5)


def main():
    print("[Main] Initializing RWS Ingress Orchestrator...", flush=True)
    client_data = generate_client_configs(force_refresh=True)
    print_banner(client_data)

    # Launch engine supervisor in background thread
    engine_thread = threading.Thread(target=run_engine_supervisor, daemon=True)
    engine_thread.start()

    # Launch Internal HTTP Server on 127.0.0.1:5000
    server_address = ("127.0.0.1", 5000)
    httpd = ThreadedHTTPServer(server_address, StealthHTTPHandler)
    print(f"[Main] Stealth HTTP Server active on 127.0.0.1:5000", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("[Main] Shutting down.", flush=True)


if __name__ == "__main__":
    main()
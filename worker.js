/**
 * OmniMesh Cloudflare Worker Edge Relay
 * =====================================
 * Relays WebSocket and XHTTP (SplitHTTP) traffic from Cloudflare Clean Anycast IPs
 * directly to your Railway deployment, completely bypassing ISP-level SNI bans on *.up.railway.app.
 *
 * Setup:
 * 1. Create a free Cloudflare Worker (or Cloudflare Pages function).
 * 2. Paste this script into the Worker editor.
 * 3. Set RAILWAY_BACKEND in Worker Variables (e.g. "your-app.up.railway.app").
 * 4. Deploy!
 */

const DEFAULT_RAILWAY_BACKEND = "your-app.up.railway.app";

export default {
    async fetch(request, env) {
        const rawBackend = env.RAILWAY_BACKEND || DEFAULT_RAILWAY_BACKEND;
        const railwayBackend = rawBackend.replace(/^https?:\/\//i, '').replace(/\/.*$/, '').trim();
        const url = new URL(request.url);

        // Neutral Health check endpoint
        if (url.pathname === "/health") {
            return new Response(JSON.stringify({ status: "healthy", service: "edge-relay" }), {
                status: 200,
                headers: { "Content-Type": "application/json" }
            });
        }

        const targetUrl = `https://${railwayBackend}${url.pathname}${url.search}`;
        const modifiedHeaders = new Headers(request.headers);
        modifiedHeaders.set("Host", railwayBackend);
        modifiedHeaders.set("X-Forwarded-Host", url.hostname);
        const clientIp = request.headers.get("CF-Connecting-IP");
        if (clientIp) {
            modifiedHeaders.set("X-Real-IP", clientIp);
            modifiedHeaders.set("X-Forwarded-For", clientIp);
        }

        // Handle WebSocket Upgrade
        const upgradeHeader = request.headers.get("Upgrade");
        if (upgradeHeader && upgradeHeader.toLowerCase() === "websocket") {
            return fetch(targetUrl, {
                method: "GET",
                headers: modifiedHeaders
            });
        }

        // Handle XHTTP (SplitHTTP) & standard HTTP requests (GET, POST, OPTIONS, etc.)
        const hasBody = request.method !== "GET" && request.method !== "HEAD";
        return fetch(targetUrl, {
            method: request.method,
            headers: modifiedHeaders,
            body: hasBody ? request.body : undefined,
            redirect: "manual"
        });
    }
};

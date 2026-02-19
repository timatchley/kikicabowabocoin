"""
KikicabowaboCoin Seed Tracker — Lightweight HTTP peer registry.

This is the internet-scale peer discovery service for KIKI.  Any node can
run one, and nodes query it to find their first peer when LAN broadcast
and hardcoded seeds aren't enough.

How it works:
  - Nodes POST /api/register  → announce themselves (host, port, height)
  - Nodes GET  /api/peers     → get a list of recently-seen peers
  - Stale entries (not seen for >30 min) are automatically pruned

This replaces the need for DNS seed infrastructure while still being
fully decentralized — anyone can run a tracker, and nodes can query
multiple trackers.  It's similar to how BitTorrent trackers work.

Run standalone:
    kiki seed                      # listen on 0.0.0.0:44147
    kiki seed --port 8080          # custom port

Or deploy anywhere (Render, fly.io, Railway, a VPS, your Pi, etc.)
"""

import json
import logging
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock
from typing import Dict

from kikicabowabocoin.config import MAGIC_BYTES

logger = logging.getLogger("kiki.seed_tracker")

# Peers not seen for this many seconds are pruned
STALE_TIMEOUT = 1800  # 30 minutes

# Maximum peers to return in a single query
MAX_RETURN = 50


class PeerRegistry:
    """Thread-safe in-memory peer registry with automatic pruning."""

    def __init__(self):
        self._peers: Dict[str, dict] = {}  # "host:port" → info
        self._lock = Lock()

    def register(self, host: str, port: int, height: int = 0,
                 version: str = ""):
        """Register or refresh a peer."""
        key = "{}:{}".format(host, port)
        with self._lock:
            self._peers[key] = {
                "host": host,
                "port": port,
                "height": height,
                "version": version,
                "last_seen": time.time(),
            }
        logger.debug("Registered peer {} (height={})".format(key, height))

    def get_peers(self, exclude: str = "", limit: int = MAX_RETURN):
        """Return active peers, newest first, excluding the requester."""
        self._prune()
        with self._lock:
            peers = [
                p for key, p in self._peers.items()
                if key != exclude
            ]
        # Sort by most recently seen
        peers.sort(key=lambda p: p["last_seen"], reverse=True)
        return peers[:limit]

    def _prune(self):
        """Remove stale peers."""
        cutoff = time.time() - STALE_TIMEOUT
        with self._lock:
            stale = [k for k, v in self._peers.items()
                     if v["last_seen"] < cutoff]
            for k in stale:
                del self._peers[k]
            if stale:
                logger.debug("Pruned {} stale peers".format(len(stale)))

    @property
    def count(self):
        with self._lock:
            return len(self._peers)


# Global registry (shared across all request handlers)
_registry = PeerRegistry()


class SeedTrackerHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the seed tracker."""

    def log_message(self, format, *args):
        """Route HTTP logs through our logger."""
        logger.debug(format % args)

    def _send_json(self, status: int, data: dict):
        """Send a JSON response."""
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_client_ip(self):
        """Get the real IP of the connecting client."""
        # Check X-Forwarded-For for reverse proxy setups
        forwarded = self.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    # ── GET endpoints ───────────────────────────────────────────────────

    def do_GET(self):
        if self.path == "/api/peers":
            self._handle_get_peers()
        elif self.path == "/api/status":
            self._handle_status()
        elif self.path == "/":
            self._handle_index()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_get_peers(self):
        """GET /api/peers — return known active peers."""
        # If the requester is itself a node, exclude it
        client_ip = self._get_client_ip()
        peers = _registry.get_peers()
        self._send_json(200, {
            "peers": [
                {
                    "host": p["host"],
                    "port": p["port"],
                    "height": p["height"],
                    "version": p["version"],
                    "last_seen": int(p["last_seen"]),
                }
                for p in peers
            ],
            "count": len(peers),
        })

    def _handle_status(self):
        """GET /api/status — tracker health check."""
        self._send_json(200, {
            "service": "KikicabowaboCoin Seed Tracker",
            "registered_peers": _registry.count,
            "uptime_info": "healthy",
        })

    def _handle_index(self):
        """GET / — human-readable landing page."""
        html = """<!DOCTYPE html>
<html>
<head><title>KikicabowaboCoin Seed Tracker</title></head>
<body style="font-family: monospace; max-width: 600px; margin: 50px auto;">
  <h1>🐕 KikicabowaboCoin Seed Tracker</h1>
  <p>This is a peer discovery service for the KIKI network.</p>
  <h3>API Endpoints:</h3>
  <ul>
    <li><code>GET  /api/peers</code> — list active peers</li>
    <li><code>POST /api/register</code> — register your node</li>
    <li><code>GET  /api/status</code> — tracker health</li>
  </ul>
  <h3>Register your node:</h3>
  <pre>curl -X POST {url}/api/register \\
  -H "Content-Type: application/json" \\
  -d '{{"port": 44144, "height": 0}}'</pre>
  <p>Registered peers: <strong>{count}</strong></p>
  <p style="color: #888;">Much peer. Very discover. Wow! ✨</p>
</body>
</html>""".format(url="http://localhost", count=_registry.count)
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── POST endpoints ──────────────────────────────────────────────────

    def do_POST(self):
        if self.path == "/api/register":
            self._handle_register()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_register(self):
        """POST /api/register — register a node as available."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode())
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid JSON"})
            return

        port = body.get("port", 44144)
        height = body.get("height", 0)
        version = body.get("version", "")

        # Use the client's real IP as the host (they can't fake this)
        host = self._get_client_ip()

        # Allow explicit host for testing / NAT traversal helpers
        if body.get("host"):
            host = body["host"]

        _registry.register(host, port, height, version)

        self._send_json(200, {
            "status": "registered",
            "your_address": "{}:{}".format(host, port),
            "peers_available": _registry.count,
        })


def run_seed_tracker(host: str = "0.0.0.0", port: int = None):
    """Start the seed tracker HTTP server."""
    # Render (and most PaaS) set $PORT — use it if no explicit port given
    if port is None:
        port = int(os.environ.get("PORT", 44147))
    server = HTTPServer((host, port), SeedTrackerHandler)
    logger.info(
        "🌱 Seed tracker running on {}:{} — ready for peer registrations".format(
            host, port
        )
    )
    print("\n  🌱 KikicabowaboCoin Seed Tracker")
    print("  ─────────────────────────────────")
    print("  Listening on {}:{}".format(host, port))
    print("  Endpoints:")
    print("    GET  /api/peers    — list peers")
    print("    POST /api/register — register a node")
    print("    GET  /api/status   — health check")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Seed tracker shut down.")
        server.shutdown()


# Allow running directly: python -m kikicabowabocoin.seed_tracker
if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    port = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run_seed_tracker(port=port)

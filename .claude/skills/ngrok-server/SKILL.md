---
name: ngrok-server
description: "Set up ngrok tunnels and public URLs for local Python servers. Use this skill whenever the user wants to expose a local server to the internet, create a public URL for a local service, set up ngrok tunnels, build webhook receivers, or share a local dev server publicly. Also trigger when the user mentions ngrok, tunneling, or needs a publicly accessible endpoint for a Python app — even if they don't say 'ngrok' explicitly but describe wanting to make localhost reachable from outside."
---

# ngrok Python Server Skill

This skill helps you create Python servers exposed to the internet via ngrok's Python SDK (`ngrok` package on PyPI). The SDK embeds ngrok directly into Python — no separate ngrok binary needed.

## Package

The official package is `ngrok` (not `pyngrok`). Install with:

```bash
pip install ngrok
# or with uv:
uv add ngrok
```

Current latest version: 1.5.x. Requires Python 3.7+.

## Authentication

ngrok requires an authtoken. The SDK reads it from the `NGROK_AUTHTOKEN` environment variable when you pass `authtoken_from_env=True`, or you can pass `authtoken="token"` directly.

Never hardcode authtokens. Use environment variables or a settings module.

## Core API: `ngrok.forward()`

This is the primary entry point. It creates a tunnel and forwards traffic to a local address.

```python
import ngrok

# Minimal — forward port 8000, read authtoken from env
listener = ngrok.forward(8000, authtoken_from_env=True)
print(f"Public URL: {listener.url()}")
```

### `forward()` parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `addr` | `str \| int` | Local address to forward to. Default: `"localhost:80"`. Can be port int, `"host:port"`, `"https://host:port"`, or `"unix:/path"` |
| `authtoken` | `str` | ngrok authtoken |
| `authtoken_from_env` | `bool` | Read authtoken from `NGROK_AUTHTOKEN` env var |
| `proto` | `str` | Protocol: `"http"` (default), `"tcp"`, `"tls"`, `"labeled"` |
| `domain` | `str` | Custom/reserved domain (e.g. `"myapp.ngrok.dev"`) |
| `basic_auth` | `str` | Basic auth as `"user:pass"` |
| `oauth_provider` | `str` | OAuth provider: `"google"`, `"github"`, `"microsoft"` |
| `oauth_allow_domains` | `str` | Comma-separated allowed email domains for OAuth |
| `schemes` | `list[str]` | URL schemes, e.g. `["https"]` or `["http", "https"]` |
| `compression` | `bool` | Enable gzip compression |
| `circuit_breaker` | `float` | Circuit breaker threshold (0.0-1.0) |
| `request_header_add` | `str` | Headers to add to requests |
| `request_header_remove` | `str` | Headers to remove from requests |
| `response_header_add` | `str` | Headers to add to responses |
| `response_header_remove` | `str` | Headers to remove from responses |
| `verify_upstream_tls` | `bool` | Verify TLS of upstream (for HTTPS backends) |
| `metadata` | `str` | Metadata string for the tunnel |
| `traffic_policy` | `str` | Traffic policy JSON string |
| `app_protocol` | `str` | Application protocol hint |
| `session_metadata` | `str` | Session metadata |

### Listener object

The object returned by `forward()` has these key methods:

- `listener.url()` — the public URL (e.g. `"https://abc123.ngrok-free.app"`)
- `listener.close()` — close this listener (async: `await listener.close()`)
- `listener.forward("localhost:9000")` — change forwarding target

### Global functions

- `ngrok.disconnect(url)` — close a specific listener by URL
- `ngrok.disconnect()` — close all listeners
- `ngrok.get_listeners()` — list all active listeners
- `ngrok.set_auth_token(token)` — set authtoken globally

## Async Builder Pattern

For more control, use the builder API:

```python
import ngrok
import asyncio

async def main():
    session = await ngrok.NgrokSessionBuilder().authtoken_from_env().connect()
    listener = await session.http_endpoint().listen()
    listener.forward("localhost:8000")
    print(f"Public URL: {listener.url()}")

    # Keep running
    await asyncio.Event().wait()

asyncio.run(main())
```

## Common Patterns

### 1. Simple HTTP server with ngrok

```python
import ngrok
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Hello from ngrok!")

def main():
    port = 8000
    server = HTTPServer(("127.0.0.1", port), Handler)

    listener = ngrok.forward(port, authtoken_from_env=True)
    logger.info(f"Public URL: {listener.url()}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        ngrok.disconnect()

if __name__ == "__main__":
    main()
```

### 2. FastAPI + ngrok

```python
import ngrok
import uvicorn
import logging
from fastapi import FastAPI

logger = logging.getLogger(__name__)
app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello from ngrok!"}

def main():
    port = 8000
    listener = ngrok.forward(port, authtoken_from_env=True)
    logger.info(f"Public URL: {listener.url()}")
    uvicorn.run(app, host="127.0.0.1", port=port)

if __name__ == "__main__":
    main()
```

### 3. Flask + ngrok

```python
import ngrok
import logging
from flask import Flask

logger = logging.getLogger(__name__)
app = Flask(__name__)

@app.route("/")
def hello():
    return "Hello from ngrok!"

def main():
    port = 5000
    listener = ngrok.forward(port, authtoken_from_env=True)
    logger.info(f"Public URL: {listener.url()}")
    app.run(host="127.0.0.1", port=port)

if __name__ == "__main__":
    main()
```

### 4. Webhook receiver

```python
import ngrok
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger(__name__)

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        payload = json.loads(body)
        logger.info(f"Received webhook: {payload}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

def main():
    port = 8080
    server = HTTPServer(("127.0.0.1", port), WebhookHandler)
    listener = ngrok.forward(port, authtoken_from_env=True)
    logger.info(f"Webhook URL: {listener.url()}")
    server.serve_forever()

if __name__ == "__main__":
    main()
```

### 5. With OAuth protection

```python
listener = ngrok.forward(
    8000,
    authtoken_from_env=True,
    oauth_provider="google",
    oauth_allow_domains="mycompany.com",
)
```

### 6. With custom domain

```python
listener = ngrok.forward(
    8000,
    authtoken_from_env=True,
    domain="myapp.ngrok.dev",
)
```

### 7. TCP tunnel (non-HTTP)

```python
listener = ngrok.forward(5432, proto="tcp", authtoken_from_env=True)
logger.info(f"TCP tunnel: {listener.url()}")
```

### 8. Traffic policy (advanced)

```python
import json

policy = json.dumps({
    "on_http_request": [{
        "actions": [{
            "type": "rate-limit",
            "config": {"capacity": 10, "rate": "60s", "bucket_key": ["conn.client_ip"]}
        }]
    }]
})

listener = ngrok.forward(8000, authtoken_from_env=True, traffic_policy=policy)
```

### 9. HTTPS backend (forwarding to local TLS)

```python
listener = ngrok.forward("https://127.0.0.1:3000", authtoken_from_env=True)
# Use verify_upstream_tls=False for self-signed certs
```

## ASGI Runner (CLI)

The `ngrok` package includes an `ngrok-asgi` CLI command:

```bash
# Uvicorn
ngrok-asgi uvicorn myapp:app

# Gunicorn
ngrok-asgi gunicorn myapp:app -k uvicorn.workers.UvicornWorker

# With auth
ngrok-asgi uvicorn myapp:app --basic-auth user:pass
```

## Key things to remember

- The `ngrok` package embeds the ngrok agent — no binary installation needed
- Always use `authtoken_from_env=True` rather than hardcoding tokens
- `listener.url()` gives you the public URL to share
- Call `ngrok.disconnect()` for cleanup
- For the server to stay up, the main thread must keep running (use `serve_forever()`, `asyncio.Event().wait()`, or similar)
- Free tier gets random subdomains; paid plans support reserved/custom domains
- The public URL changes on each restart unless you use a reserved domain

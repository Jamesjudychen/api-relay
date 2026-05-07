<div align="center">
  <h1>⚡ API Relay</h1>
  <p><em>A high-performance, general-purpose API relay/proxy service</em></p>
  <p>
    <a href="#features">Features</a> •
    <a href="#quick-start">Quick Start</a> •
    <a href="#configuration">Configuration</a> •
    <a href="#api-reference">API Reference</a> •
    <a href="#deployment">Deployment</a>
  </p>
  <p>
    <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+" />
    <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License" />
  </p>
</div>

---

**API Relay** is a lightweight, high-performance reverse proxy for API services. It sits between your clients and upstream API providers (OpenAI, Anthropic, or any HTTP API), handling authentication, rate limiting, request routing, and logging — all through a simple YAML configuration file.

## Features

- **🔑 API Key Management** — Multi-user key authentication with admin/user roles, expiry, and per-key rate limit overrides
- **🔄 Multi-Provider Routing** — Route requests based on path prefix, headers, or request body content
- **⏱️ Rate Limiting** — Sliding window algorithm with per-key and per-IP limits
- **📡 Streaming Support** — Transparent SSE/streaming response forwarding
- **📊 Request Logging** — Full request/response logging with SQLite (batch async writes)
- **⚡ Hot-Reload Config** — Update routes and providers without restarting
- **🔌 Provider Agnostic** — Works with OpenAI, Anthropic, OpenRouter, or any HTTP API
- **🐍 Pure Python** — Built on FastAPI + httpx, easy to extend

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/Jamesjudychen/api-relay.git
cd api-relay

# Install with pip
pip install .

# Or with uv (recommended)
uv sync
```

### Run

```bash
# Start with default config
api-relay

# Or via Python module
python -m api_relay

# Specify a custom config file
api-relay --config /path/to/config.yaml

# Development mode with hot-reload
api-relay --reload
```

### Verify

```bash
# Health check
curl http://localhost:9000/health

# Create an admin API key (requires bootstrap key from config)
curl -X POST http://localhost:9000/admin/api-keys \
  -H "Authorization: Bearer ag_your_admin_key_here_change_me" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Key", "role": "user"}'
```

## Configuration

The service is configured via a single YAML file. Here's a minimal example:

```yaml
# api_relay.yaml
host: "127.0.0.1"
port: 9000

# Bootstrap admin key (change this!)
api_keys:
  admin_keys:
    - "ag_your_admin_key_here_change_me"

# Upstream providers
providers:
  openai:
    base_url: "https://api.openai.com/v1"
    default_headers:
      Authorization: "Bearer ${OPENAI_API_KEY}"

# Route rules (first match wins)
routes:
  - name: "OpenAI Proxy"
    match_type: "path_prefix"
    match_value: "/openai"
    target_url: "https://api.openai.com/v1"
    strip_prefix: true
```

### Route Matching Types

| Type | Description | Example |
|------|-------------|---------|
| `path_prefix` | Match by URL prefix | `/openai/*` → `https://api.openai.com/v1/*` |
| `header` | Match by request header | `X-Provider: custom` → `https://custom.api.com` |
| `body_jsonpath` | Match by request body field | `$.model=claude-*` → `https://api.anthropic.com` |

### Full Configuration Reference

See [api_relay/api_relay.yaml](api_relay/api_relay.yaml) for all available options, including rate limiting, CORS, log retention, and more.

### Environment Variables

Values in the config file support `${VAR_NAME}` syntax for environment variable substitution:

```yaml
providers:
  openai:
    default_headers:
      Authorization: "Bearer ${OPENAI_API_KEY}"
```

## API Reference

### Proxy Endpoints

```
ANY /{path:path}  →  Forwarded to matched upstream provider
```

### Admin API (requires admin API key)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Public health check |
| `GET` | `/admin/api-keys` | List all API keys |
| `POST` | `/admin/api-keys` | Create a new API key |
| `GET` | `/admin/api-keys/{id}` | Get key details |
| `PATCH` | `/admin/api-keys/{id}` | Update key attributes |
| `DELETE` | `/admin/api-keys/{id}` | Soft-delete (deactivate) key |
| `GET` | `/admin/stats` | Request statistics |

### Interactive API Docs

When the service is running, visit:
- Swagger UI: [http://localhost:9000/docs](http://localhost:9000/docs)
- ReDoc: [http://localhost:9000/redoc](http://localhost:9000/redoc)

## Deployment

### Production (with systemd)

```ini
[Unit]
Description=API Relay Service
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/opt/api-relay
Environment=OPENAI_API_KEY=sk-...
ExecStart=/usr/local/bin/api-relay --config /opt/api-relay/config.yaml
Restart=always

[Install]
WantedBy=multi-user.target
```

### Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install .
EXPOSE 9000
CMD ["api-relay"]
```

### Reverse Proxy (Nginx)

```nginx
server {
    listen 443 ssl;
    server_name api.example.com;

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Development

```bash
# Install dev dependencies
pip install ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=api_relay
```

## Architecture

```
Client Request
  │
  ▼
┌──────────────────────┐
│ LoggingMiddleware    │  ← Records timing & metadata
├──────────────────────┤
│ AuthMiddleware       │  ← Validates Bearer token
├──────────────────────┤
│ RateLimitMiddleware  │  ← Sliding window rate check
├──────────────────────┤
│ RouterEngine         │  ← Match route rules
├──────────────────────┤
│ Proxy Forwarder      │  ← httpx → upstream
└──────────────────────┘
  │
  ▼
Client Response
```

## License

MIT

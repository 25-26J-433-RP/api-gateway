# API Gateway

Lightweight FastAPI-based API gateway that proxies requests to upstream services
based on `routes.json`. This repository contains api gateway used
for sinhala essay grading system.

**Contents**
- `gateway.py` - main FastAPI gateway application
- `routes.json` - mapping of route prefixes to upstream URLs (can reference env secrets)
- `.env` - environment variables (upstream URLs)
- `requirements.txt` - Python dependencies

**Prerequisites**
- Python 3.11+ installed
- `pip` available

Setup
1. Create a virtualenv (recommended) and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Provide upstream URLs and any secrets in a `.env` file in the project root.
   Example `.env`:

```dotenv
SINHALA_VISUAL_MAPPING_SERVICE_URL=
SINHALA_TEXT_FEEDBACK_SERVICE_URL=
# Optional: API_KEY=mysecretkey
```

How routes work
- `routes.json` maps a route prefix to an upstream. Example:

```json
{
  "/sinhala-visual-mapping-service": "secret:SINHALA_VISUAL_MAPPING_SERVICE_URL",
  "/sinhala-text-feedback-service": "secret:SINHALA_TEXT_FEEDBACK_SERVICE_URL"
}
```

- The gateway resolves `secret:NAME` by reading the environment variable `NAME`.
- If a client requests exactly the prefix (e.g. `GET /sinhala-visual-mapping-service`)
  and the upstream contains a non-root path (for example `.../health`), the
  gateway will request the upstream as-is. Otherwise the path suffix requested
  by the client is appended to the upstream URL.

Run the gateway

Start the server (development):

```bash
# no auto-reload
python -m uvicorn gateway:APP --host 127.0.0.1 --port 8000

# or with reload while developing
python -m uvicorn gateway:APP --host 0.0.0.0 --port 8000 --reload
```

Run in background (example):

```bash
# nohup example (writes logs to /tmp/gateway.log)
nohup python -m uvicorn gateway:APP --host 0.0.0.0 --port 8000 > /tmp/gateway.log 2>&1 &
echo $! > /tmp/gateway.pid
```

Test endpoints

Get route mappings:

```bash
curl -i http://127.0.0.1:8000/routes
```

Proxy to an upstream (example):

```bash
curl -i http://127.0.0.1:8000/sinhala-visual-mapping-service
```

Next steps / Improvements
- Add unit tests for the URL-joining logic and header forwarding
- Add health-check endpoints for the gateway itself
- Add structured logging and metrics

License
- See `LICENSE` in the repository root.

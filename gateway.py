import json
import os
from typing import Optional

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
from dotenv import load_dotenv

load_dotenv()

APP = FastAPI(title="Simple Python API Gateway")

# ------------------------------
#  CORS
# ------------------------------
APP.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8081",
        "https://akura.vercel.app",
        "https://akura-qa.vercel.app",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(__file__)
ROUTES_FILE = os.path.join(BASE_DIR, "routes.json")

API_KEY = os.getenv("API_KEY")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10"))


def load_routes():
    try:
        with open(ROUTES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # normalize prefixes (no trailing slash)
            return {k.rstrip("/"): v.rstrip("/") for k, v in data.items()}
    except FileNotFoundError:
        return {}


ROUTES = load_routes()

# cache for resolved secret values
_SECRET_CACHE = {}


def resolve_upstream_value(value: str) -> str:
    """Resolve an upstream value. If value starts with 'secret:NAME', read env var NAME.
    Otherwise return the value as-is.
    """
    if not isinstance(value, str):
        return value
    if not value.startswith("secret:"):
        return value
    name = value.split("secret:", 1)[1]
    if not name:
        raise RuntimeError("Invalid secret reference in routes: missing name")
    # cache lookup
    if name in _SECRET_CACHE:
        return _SECRET_CACHE[name]
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Secret for '{name}' not found in environment")
    _SECRET_CACHE[name] = val.rstrip("/")
    return _SECRET_CACHE[name]


def find_upstream(path: str) -> Optional[tuple]:
    # find longest matching prefix
    matches = [(prefix, ROUTES[prefix]) for prefix in ROUTES.keys() if path == prefix or path.startswith(prefix + "/")]
    if not matches:
        return None
    matches.sort(key=lambda x: len(x[0]), reverse=True)
    prefix, upstream = matches[0]
    # if upstream references secret, resolve it now
    try:
        upstream = resolve_upstream_value(upstream)
    except RuntimeError:
        # bubble up missing secret to caller
        raise
    suffix = path[len(prefix):]
    if not suffix:
        suffix = "/"
    return prefix, upstream, suffix


HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"}


@APP.get("/routes")
def routes():
    return ROUTES


@APP.middleware("http")
async def check_api_key(request: Request, call_next):
    if API_KEY:
        key = request.headers.get("x-api-key")
        if not key or key != API_KEY:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


@APP.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy(full_path: str, request: Request):
    path = "/" + full_path
    found = find_upstream(path)
    if not found:
        raise HTTPException(status_code=404, detail="No upstream matching path")

    prefix, upstream, suffix = found
    # build upstream URL safely (avoid adding an extra slash when upstream
    # already contains a path). Use urlparse to detect whether the
    # configured upstream contains its own path component.
    from urllib.parse import urlparse

    # suffix == "/" means caller requested exactly the prefix. If the
    # upstream already contains a non-root path (e.g. .../health), use the
    # upstream as-is. Otherwise ensure there is a single trailing slash.
    if suffix == "/":
        parsed = urlparse(upstream)
        if parsed.path and parsed.path != "/":
            target_url = upstream
        else:
            target_url = upstream + "/"
    else:
        # join without duplicating slashes
        target_url = upstream.rstrip("/") + "/" + suffix.lstrip("/")

    # prepare headers
    # do not forward hop-by-hop headers or the original Host header (upstream
    # needs Host to match its own hostname); let httpx set Host from the
    # target URL.
    req_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP and k.lower() != "host"
    }
    # set X-Forwarded-For
    client_host = request.client.host if request.client else ""
    if client_host:
        existing = req_headers.get("x-forwarded-for")
        req_headers["x-forwarded-for"] = f"{existing}, {client_host}" if existing else client_host

    body = await request.body()

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.request(
                request.method,
                target_url,
                params=request.query_params,
                headers=req_headers,
                content=body,
                timeout=REQUEST_TIMEOUT,
                follow_redirects=False,
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=str(e))

    # filter response headers
    headers = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP}

    return Response(content=resp.content, status_code=resp.status_code, headers=headers, media_type=resp.headers.get("content-type"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("gateway:APP", host="0.0.0.0", port=8000, reload=True)

"""Logs estruturados (JSON, com project_id/job_id), request-id e métricas simples em formato Prometheus."""
import json
import logging
import sys
import threading
import time
import uuid
from collections import Counter

from fastapi import FastAPI, Request

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}
http_counter: Counter = Counter()
http_time: Counter = Counter()
_lock = threading.Lock()
STARTED = time.time()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname, "logger": record.name,
               "msg": record.getMessage()}
        out.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(getattr(h, "_kontrul", False) for h in root.handlers):
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    h._kontrul = True  # type: ignore[attr-defined]
    root.handlers = [h]
    root.setLevel(level)


def install(app: FastAPI) -> None:
    log = logging.getLogger("kontrul.http")

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        t0 = time.perf_counter()
        status = 500
        try:
            resp = await call_next(request)
            status = resp.status_code
            resp.headers["X-Request-ID"] = rid
            return resp
        finally:
            ms = (time.perf_counter() - t0) * 1000
            route = request.scope.get("route")
            tpl = getattr(route, "path", "unmatched")  # template (sem ids) para não explodir cardinalidade
            with _lock:
                http_counter[(request.method, tpl, status)] += 1
                http_time[(request.method, tpl)] += ms / 1000
            if request.url.path not in ("/health", "/health/ready", "/metrics"):
                log.info("request", extra={"request_id": rid, "method": request.method, "path": request.url.path,
                                           "status": status, "ms": round(ms, 1)})


def render_metrics(job_counts: list[tuple[str, str, int]]) -> str:
    L = ["# HELP kontrul_uptime_seconds Tempo desde o início do processo", "# TYPE kontrul_uptime_seconds gauge",
         f"kontrul_uptime_seconds {time.time() - STARTED:.0f}",
         "# HELP kontrul_jobs Jobs por tipo e estado", "# TYPE kontrul_jobs gauge"]
    L += [f'kontrul_jobs{{kind="{k}",state="{s}"}} {n}' for k, s, n in job_counts]
    L += ["# HELP kontrul_http_requests_total Requisições HTTP", "# TYPE kontrul_http_requests_total counter"]
    with _lock:
        L += [f'kontrul_http_requests_total{{method="{m}",route="{r}",status="{st}"}} {n}' for (m, r, st), n in sorted(http_counter.items())]
        L += ["# TYPE kontrul_http_request_seconds_sum counter"]
        L += [f'kontrul_http_request_seconds_sum{{method="{m}",route="{r}"}} {v:.3f}' for (m, r), v in sorted(http_time.items())]
    return "\n".join(L) + "\n"

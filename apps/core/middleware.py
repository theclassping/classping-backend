"""Request timing instrumentation for API responses."""

import time
from contextlib import ExitStack

from django.conf import settings
from django.db import connections


class _QueryTimer:
    """Database execute wrapper that counts queries and sums their duration."""

    def __init__(self):
        self.count = 0
        self.duration = 0.0

    def __call__(self, execute, sql, params, many, context):
        start = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            self.duration += time.perf_counter() - start
            self.count += 1


class ServerTimingMiddleware:
    """Add a Server-Timing header with total server time and DB usage.

    Example header:
        Server-Timing: app;dur=41.2, db;dur=12.7;desc="9 queries"

    "app" is the time spent inside Django (all middleware, auth, view and
    serialization); the rest of a client's observed latency is network,
    TLS and proxy time. Only requests under SERVER_TIMING_PATH_PREFIX are
    instrumented, and SERVER_TIMING_ENABLED=False turns it off entirely.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = getattr(settings, "SERVER_TIMING_ENABLED", True)
        self.path_prefix = getattr(settings, "SERVER_TIMING_PATH_PREFIX", "/api/")

    def __call__(self, request):
        if not self.enabled or not request.path.startswith(self.path_prefix):
            return self.get_response(request)

        timer = _QueryTimer()
        start = time.perf_counter()
        with ExitStack() as stack:
            for connection in connections.all():
                stack.enter_context(connection.execute_wrapper(timer))
            response = self.get_response(request)
        total_ms = (time.perf_counter() - start) * 1000

        metrics = [
            f"app;dur={total_ms:.1f}",
            f'db;dur={timer.duration * 1000:.1f};desc="{timer.count} queries"',
        ]
        existing = response.get("Server-Timing")
        if existing:
            metrics.insert(0, existing)
        response["Server-Timing"] = ", ".join(metrics)
        return response

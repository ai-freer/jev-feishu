"""Dependency-injectable JSON transport with bounded, sanitized failures."""

import json
from time import monotonic
from urllib import error, request


class ModelError(RuntimeError):
    pass


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_json(req, timeout):
    try:
        with request.build_opener(_NoRedirect()).open(req, timeout=timeout) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ModelError("invalid_response")
            data = json.loads(raw)
    except error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ModelError("unauthorized") from None
        if exc.code == 429:
            raise ModelError("rate_limited") from None
        raise ModelError("http_error") from None
    except (error.URLError, TimeoutError, OSError):
        raise ModelError("connection_error") from None
    except (ValueError, TypeError):
        raise ModelError("invalid_response") from None
    if not isinstance(data, dict):
        raise ModelError("invalid_response")
    return data


def get_json(url: str, timeout: float, *, headers=None) -> dict:
    return _read_json(request.Request(url, headers=headers or {}, method="GET"), timeout)


def post_json(url: str, headers: dict[str, str], payload: dict, timeout: float) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return _read_json(request.Request(url, data=body, headers=headers, method="POST"), timeout)


def post_stream(url, headers, payload, timeout):
    """Yield bounded SSE JSON events; never follow credential-bearing redirects."""
    req = request.Request(url, data=json.dumps(payload).encode("utf-8"),
                          headers={**headers, "accept": "text/event-stream"}, method="POST")
    try:
        with request.build_opener(_NoRedirect()).open(req, timeout=timeout) as response:
            total = 0
            deadline = monotonic() + timeout
            parts = []
            while True:
                line = response.readline(1024 * 1024 + 1)
                if monotonic() > deadline:
                    raise ModelError("connection_error")
                total += len(line)
                if total > 8 * 1024 * 1024 or len(line) > 1024 * 1024:
                    raise ModelError("invalid_response")
                if not line or not line.strip():
                    if parts:
                        raw = "\n".join(parts)
                        parts = []
                        if raw == "[DONE]":
                            return
                        value = json.loads(raw)
                        if not isinstance(value, dict):
                            raise ModelError("invalid_response")
                        yield value
                    if not line:
                        return
                elif line.startswith(b"data:"):
                    parts.append(line[5:].decode("utf-8").strip())
    except error.HTTPError as exc:
        raise ModelError("unauthorized" if exc.code in (401, 403) else
                         "rate_limited" if exc.code == 429 else "http_error") from None
    except (error.URLError, TimeoutError, OSError):
        raise ModelError("connection_error") from None
    except (ValueError, TypeError, UnicodeError):
        raise ModelError("invalid_response") from None

"""Dependency-injectable JSON transport with bounded, sanitized failures."""

import json
from urllib import error, request


class ModelError(RuntimeError):
    pass


def get_json(url: str, timeout: float) -> dict:
    try:
        with request.urlopen(url, timeout=timeout) as response:
            data = json.load(response)
    except error.HTTPError:
        raise ModelError("http_error") from None
    except (error.URLError, TimeoutError, OSError):
        raise ModelError("connection_error") from None
    except (ValueError, TypeError):
        raise ModelError("invalid_response") from None
    if not isinstance(data, dict):
        raise ModelError("invalid_response")
    return data


def post_json(url: str, headers: dict[str, str], payload: dict, timeout: float) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            data = json.load(response)
    except error.HTTPError as exc:
        if exc.code == 401:
            raise ModelError("unauthorized") from None
        if exc.code == 429:
            raise ModelError("rate_limited") from None
        raise ModelError("http_error") from None
    except (error.URLError, TimeoutError):
        raise ModelError("connection_error") from None
    except (ValueError, TypeError):
        raise ModelError("invalid_response") from None
    if not isinstance(data, dict):
        raise ModelError("invalid_response")
    return data

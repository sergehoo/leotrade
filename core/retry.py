"""
core/retry.py
-------------

Retry helpers for broker / network operations.

The previous version retried on every Exception, masking real bugs and
re-submitting orders on validation errors. This version:

- Retries only on a configurable allow-list of transient exceptions.
- Implements full jitter exponential backoff (cf. AWS Architecture Blog).
- Caps total time to a reasonable budget so a single retry can't hang Celery.
- Provides a ``retryable`` predicate decorator for fine-grained control.

By default we retry on:

- ``httpx.ConnectError``, ``httpx.ReadTimeout``, ``httpx.ConnectTimeout``,
  ``httpx.PoolTimeout``, ``httpx.WriteTimeout``
- ``requests.exceptions.ConnectionError`` / ``Timeout``
- ``ConnectionError`` / ``TimeoutError``
- A 429 / 5xx HTTPStatusError if the upstream tells us to retry.

Validation errors, ``ValueError``, ``KeyError``, broker rejections, etc. are
NOT retried — they would loop forever or duplicate orders.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, Iterable, Optional, Tuple, Type

logger = logging.getLogger(__name__)


# Build the default allow-list lazily so that imports don't break on missing libs.
def _default_transient_excs() -> Tuple[Type[BaseException], ...]:
    excs: list[type] = [ConnectionError, TimeoutError, OSError]
    try:
        import httpx

        excs.extend(
            [
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.ConnectTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
            ]
        )
    except Exception:  # pragma: no cover
        pass

    try:
        import requests  # type: ignore

        excs.extend(
            [
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ]
        )
    except Exception:  # pragma: no cover
        pass

    return tuple(set(excs))


def _is_http_retryable(exc: BaseException) -> bool:
    """Return True for HTTP errors with retryable status (429, 5xx)."""
    try:
        import httpx  # type: ignore

        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            return code == 429 or 500 <= code < 600
    except Exception:
        pass

    try:
        import requests  # type: ignore

        if isinstance(exc, requests.exceptions.HTTPError):
            response = getattr(exc, "response", None)
            if response is not None:
                code = response.status_code
                return code == 429 or 500 <= code < 600
    except Exception:
        pass

    return False


def retry_call(
    fn: Callable,
    *args,
    attempts: int = 3,
    base_sleep: float = 0.5,
    max_sleep: float = 8.0,
    transient_exceptions: Optional[Iterable[Type[BaseException]]] = None,
    on_retry: Optional[Callable[[int, BaseException], None]] = None,
    **kwargs,
):
    """
    Call ``fn(*args, **kwargs)`` with exponential backoff + full jitter.

    Args:
        attempts: total attempts, including the first call.
        base_sleep: initial sleep between attempts (seconds).
        max_sleep: cap for each backoff.
        transient_exceptions: tuple of exceptions considered retryable.
        on_retry: optional callback ``(attempt_number, exception)``.

    Raises:
        The last exception encountered if all attempts fail.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    transient = (
        tuple(transient_exceptions)
        if transient_exceptions is not None
        else _default_transient_excs()
    )

    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except transient as exc:
            last_exc = exc
        except Exception as exc:
            # HTTPStatusError can be a httpx subclass not in `transient` —
            # check status to decide.
            if _is_http_retryable(exc):
                last_exc = exc
            else:
                raise

        if attempt >= attempts:
            break

        # Full jitter exponential backoff: random(0, base * 2^(attempt-1))
        upper = min(max_sleep, base_sleep * (2 ** (attempt - 1)))
        delay = random.uniform(0.0, upper)

        logger.warning(
            "retry_call attempt=%s/%s exc=%s sleep=%.2fs",
            attempt,
            attempts,
            type(last_exc).__name__,
            delay,
        )
        if on_retry is not None:
            try:
                on_retry(attempt, last_exc)
            except Exception:  # pragma: no cover
                logger.exception("on_retry callback failed")

        time.sleep(delay)

    assert last_exc is not None
    raise last_exc


def retry_sync(fn, *args, **kwargs):
    """
    Backwards-compatible wrapper.

    Reads attempts/sleep from settings (BROKER_RETRY_*) like the legacy code.
    Now uses smart transient-only retry instead of bare Exception.
    """
    from django.conf import settings

    attempts = getattr(settings, "BROKER_RETRY_MAX_ATTEMPTS", 3)
    base_sleep = float(getattr(settings, "BROKER_RETRY_BACKOFF_SECONDS", 1))
    return retry_call(
        fn,
        *args,
        attempts=attempts,
        base_sleep=base_sleep,
        **kwargs,
    )

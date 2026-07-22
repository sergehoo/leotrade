"""
core/concurrency.py
-------------------

Outils de concurrence pour Lyneci.

Fournit :

- ``RedisLock`` : verrou distribué SET NX EX + token (acquit/release sûr)
  utilisable comme context manager.
- ``redis_lock`` : helper context manager simplifié.
- ``with_lock`` : décorateur pour protéger une fonction (ex: tâche Celery).
- ``RuntimeMutex``: fallback ``threading.RLock`` si Redis indisponible.

Usage typique
=============

Verrou broker MT5 (le module MetaTrader5 est un singleton non thread-safe) :

.. code-block:: python

    from core.concurrency import redis_lock

    with redis_lock("broker:mt5:account:42", timeout=30):
        # appels mt5.* protégés ici

Protection d'une tâche Celery périodique contre le chevauchement :

.. code-block:: python

    from core.concurrency import with_lock

    @shared_task
    @with_lock("scan_market_1m", timeout=55)
    def scan_market_1m_task():
        ...

Notes
-----

- Le timeout doit toujours être > durée maximale attendue de la section critique.
- Si la lib ``redis`` n'est pas dispo, on retombe sur un RLock process-local
  (acceptable en dev mono-worker, dangereux en prod multi-worker → log warning).
"""

from __future__ import annotations

import functools
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

logger = logging.getLogger(__name__)


try:
    import redis as _redis_lib
except Exception:  # pragma: no cover
    _redis_lib = None


_LUA_RELEASE = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

_LUA_EXTEND = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], ARGV[2])
else
    return 0
end
"""


class LockAcquireError(RuntimeError):
    """Raised when a distributed lock cannot be acquired."""


class _LocalLockRegistry:
    """Fallback registry of named ``threading.RLock`` (dev only)."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.Lock()

    def get(self, name: str) -> threading.RLock:
        with self._guard:
            lock = self._locks.get(name)
            if lock is None:
                lock = threading.RLock()
                self._locks[name] = lock
            return lock


_local_registry = _LocalLockRegistry()


def _get_redis_client():
    """Build a redis client from settings, lazily."""
    if _redis_lib is None:
        return None
    try:
        from django.conf import settings

        url = getattr(settings, "REDIS_URL", None) or os.environ.get(
            "REDIS_URL", "redis://127.0.0.1:6379/1"
        )
        return _redis_lib.Redis.from_url(url, socket_timeout=5, socket_connect_timeout=5)
    except Exception:
        logger.exception("Failed to build Redis client for distributed lock.")
        return None


class RedisLock:
    """
    Verrou distribué Redis (SET NX EX + token).

    Le token random évite qu'un client A ne libère un verrou tenu par un client B
    après expiration tardive (cas classique de double-release).

    Args:
        name: nom logique du verrou (sera préfixé ``lyneci:lock:``).
        timeout: TTL du verrou en secondes (auto-release si crash).
        blocking: si True, attend ``blocking_timeout`` secondes max.
        blocking_timeout: temps max d'attente.
        sleep: temps entre tentatives quand blocking.
    """

    PREFIX = "lyneci:lock:"

    def __init__(
        self,
        name: str,
        timeout: int = 30,
        blocking: bool = False,
        blocking_timeout: float = 0.0,
        sleep: float = 0.1,
    ) -> None:
        if not name:
            raise ValueError("RedisLock name is required.")
        self.name = f"{self.PREFIX}{name}"
        self.timeout = max(1, int(timeout))
        self.blocking = bool(blocking)
        self.blocking_timeout = float(blocking_timeout)
        self.sleep = float(sleep)
        self._token = uuid.uuid4().hex
        self._client = _get_redis_client()
        self._held = False
        self._fallback_lock: Optional[threading.RLock] = None

    # ------------------------------------------------------------------ public

    def acquire(self) -> bool:
        if self._client is None:
            logger.warning(
                "Redis unavailable, falling back to process-local lock for %s",
                self.name,
            )
            self._fallback_lock = _local_registry.get(self.name)
            acquired = self._fallback_lock.acquire(
                blocking=self.blocking,
                timeout=self.blocking_timeout if self.blocking else -1,
            )
            self._held = bool(acquired)
            return self._held

        deadline = time.monotonic() + self.blocking_timeout
        while True:
            ok = self._client.set(self.name, self._token, nx=True, ex=self.timeout)
            if ok:
                self._held = True
                return True
            if not self.blocking:
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(self.sleep)

    def release(self) -> None:
        if not self._held:
            return
        try:
            if self._fallback_lock is not None:
                self._fallback_lock.release()
                return
            if self._client is not None:
                self._client.eval(_LUA_RELEASE, 1, self.name, self._token)
        except Exception:
            logger.exception("Failed to release lock %s", self.name)
        finally:
            self._held = False

    def extend(self, additional_seconds: int) -> bool:
        """Extend the TTL of the lock if still owned."""
        if not self._held or self._client is None:
            return False
        try:
            res = self._client.eval(
                _LUA_EXTEND, 1, self.name, self._token, str(int(additional_seconds))
            )
            return bool(res)
        except Exception:
            logger.exception("Failed to extend lock %s", self.name)
            return False

    # ---------------------------------------------------------- context mgr

    def __enter__(self) -> "RedisLock":
        if not self.acquire():
            raise LockAcquireError(f"Cannot acquire lock {self.name}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


@contextmanager
def redis_lock(
    name: str,
    *,
    timeout: int = 30,
    blocking: bool = False,
    blocking_timeout: float = 0.0,
) -> Iterator[Optional[RedisLock]]:
    """
    Context manager for ``RedisLock``.

    Yields the lock if acquired, ``None`` otherwise (so callers can check).

    Example:
        with redis_lock("scan_market_1m", timeout=55) as lock:
            if lock is None:
                return  # already running elsewhere
            ...
    """
    lock = RedisLock(
        name,
        timeout=timeout,
        blocking=blocking,
        blocking_timeout=blocking_timeout,
    )
    if not lock.acquire():
        yield None
        return
    try:
        yield lock
    finally:
        lock.release()


def with_lock(
    name: str,
    *,
    timeout: int = 30,
    blocking: bool = False,
    blocking_timeout: float = 0.0,
    on_busy=None,
) -> Callable:
    """
    Decorator to wrap a callable in a Redis lock.

    If the lock is already held and ``blocking=False``, ``on_busy`` is invoked
    (or returns a sentinel dict ``{"locked": True, "skipped": True}``).

    Useful for Celery beat tasks to prevent overlapping runs.
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            lock = RedisLock(
                name,
                timeout=timeout,
                blocking=blocking,
                blocking_timeout=blocking_timeout,
            )
            if not lock.acquire():
                if on_busy is not None:
                    return on_busy(*args, **kwargs)
                logger.info("Lock %s busy — skipping %s", name, fn.__name__)
                return {"locked": True, "skipped": True, "name": name}
            try:
                return fn(*args, **kwargs)
            finally:
                lock.release()

        return wrapper

    return decorator

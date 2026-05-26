"""
core/redis_lock.py
==================

Helper unique pour appliquer un lock Redis sur les tâches Celery
critiques (anti-chevauchement).

Usage :
    from core.redis_lock import single_run

    @shared_task
    def my_task():
        with single_run("lock:my_task", ttl=55):
            # corps de la tâche
            ...
"""

from __future__ import annotations

from contextlib import contextmanager

from django.core.cache import cache


@contextmanager
def single_run(name: str, ttl: int = 55):
    """
    Acquiert un lock Redis non-bloquant. Si déjà tenu, le bloc `yield`
    est skipped (la tâche s'exécute "à vide" — log à ajouter dans le caller).

    :param name: clé du lock (str unique par tâche)
    :param ttl: durée maximale du lock en secondes (auto-release si crash)
    """
    try:
        lock = cache.lock(name, timeout=ttl, blocking_timeout=0)
    except Exception:
        # Cache backend ne supporte pas le lock natif → noop
        yield True
        return

    acquired = False
    try:
        acquired = lock.acquire(blocking=False)
        yield acquired
    finally:
        if acquired:
            try:
                lock.release()
            except Exception:
                pass

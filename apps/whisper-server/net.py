"""Quién puede usar el servidor. Sin dependencias: se prueba sin aiohttp."""
from __future__ import annotations

from urllib.parse import urlparse


def origin_allowed(origin: str | None, extra: list[str]) -> bool:
    """Solo páginas abiertas en este ordenador (o las que se permitan con --allow-origin)."""
    if not origin or origin == "null":          # archivo abierto con doble clic
        return True
    if origin in extra:
        return True
    try:
        return urlparse(origin).hostname in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        return False

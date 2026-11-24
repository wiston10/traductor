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


LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

# Lo único que pueden abrir los móviles de la sala. Todo lo demás (audio, corrección,
# frases guardadas, modo idea) solo desde este ordenador.
PUBLIC_PATHS = {"/oyente", "/ws/oyente", "/oyente.webmanifest"}


def is_local(remote: str | None) -> bool:
    return (remote or "") in LOOPBACK


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS


def same_origin(origin: str | None, host: str | None) -> bool:
    """La página que conecta es la que sirve este mismo servidor (los móviles)."""
    if not origin or not host:
        return False
    try:
        return urlparse(origin).netloc.lower() == host.lower()
    except ValueError:
        return False


def lan_ip() -> str | None:
    """Dirección de este ordenador en la red local (la que deben usar los móviles)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))      # no envía nada: solo elige la interfaz de salida
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()

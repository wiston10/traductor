#!/usr/bin/env python3
"""
Descarga Biblias antiguas de dominio público (una vez) para generar el glosario bíblico.

Fuente: https://github.com/scrollmapper/bible_databases (formato CSV: Book,Chapter,Verse,Text)
Uso:    python3 tools/fetch_bibles.py
"""
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/scrollmapper/bible_databases/master/formats/csv/"
BIBLES = {
    "es": ("SpaRV", "Reina-Valera 1909"),
    "de": ("GerElb1905", "Elberfelder 1905"),
    "fr": ("FreCrampon", "Bible Crampon 1923"),
    "en": ("ASV", "American Standard Version 1901"),
}
OUT = Path(__file__).resolve().parent.parent / "data" / "bibles"


def download(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.read()
    except Exception as exc:  # noqa: BLE001
        # Python de python.org en Mac no trae certificados: usar curl, que sí los tiene
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc) or not shutil.which("curl"):
            raise
        return subprocess.run(["curl", "-fsSL", "--max-time", "180", url],
                              check=True, capture_output=True).stdout


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ok = True
    for lang, (code, name) in BIBLES.items():
        dest = OUT / f"{lang}.csv"
        if dest.exists() and dest.stat().st_size > 1_000_000:
            print(f"✔ {lang}: {name} (ya descargada)")
            continue
        print(f"↓ {lang}: {name}…", end=" ", flush=True)
        try:
            data = download(BASE + code + ".csv")
            if not data.startswith(b"Book,Chapter,Verse,Text"):
                raise ValueError("formato inesperado")
            dest.write_bytes(data)
            print(f"{len(data) / 1e6:.1f} MB")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"ERROR: {exc}")
    print("Listo." if ok else "Hubo errores: revisa la conexión y vuelve a ejecutar.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

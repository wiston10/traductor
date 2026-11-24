"""
Palabras de dialecto suizo que a veces se cuelan en la transcripción → alemán estándar.

La lista es NUESTRA: sale de las correcciones hechas en /corregir
(python3 evaluate.py --sugerir-dialecto) y una persona decide qué entra en
vocab/dialecto-de.json. No se aplica nada que nadie haya revisado.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_FILE = HERE / "vocab" / "dialecto-de.json"


class Dialect:
    def __init__(self, mapping: dict[str, str] | None = None):
        self.mapping = {k.lower(): v for k, v in (mapping or {}).items() if k and v}
        keys = sorted(self.mapping, key=len, reverse=True)
        self.re = re.compile(r"(?<!\w)(" + "|".join(map(re.escape, keys)) + r")(?!\w)", re.IGNORECASE) \
            if keys else None

    @classmethod
    def load(cls, path: Path = DEFAULT_FILE) -> "Dialect":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data.get("mappings", {}))

    def __len__(self) -> int:
        return len(self.mapping)

    def apply(self, text: str) -> str:
        if not self.re:
            return text

        def repl(m: re.Match) -> str:
            word = m.group(0)
            out = self.mapping[word.lower()]
            return out[:1].upper() + out[1:] if word[:1].isupper() else out
        return self.re.sub(repl, text)

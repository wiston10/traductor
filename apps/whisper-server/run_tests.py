#!/usr/bin/env python3
"""
Ejecuta todas las pruebas (test_*.py) sin necesitar pytest ni modelos.
Uso:  python3 run_tests.py        (desde la raíz: npm test)
Una prueba que devuelve "SKIP" se salta (p. ej. falta aiohttp en esta máquina).
"""
import importlib
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main() -> int:
    passed = failed = skipped = 0
    for path in sorted(HERE.glob("test_*.py")):
        mod = importlib.import_module(path.stem)
        for name, fn in vars(mod).items():
            if not name.startswith("test_") or not callable(fn):
                continue
            try:
                result = fn()
            except Exception:  # noqa: BLE001
                failed += 1
                print(f"FALLA {path.stem}.{name}")
                traceback.print_exc()
                continue
            if result == "SKIP":
                skipped += 1
                print(f"SALTA {path.stem}.{name}")
            else:
                passed += 1
                print(f"OK    {path.stem}.{name}")
    print(f"\n{passed} correctas, {failed} fallidas, {skipped} saltadas")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

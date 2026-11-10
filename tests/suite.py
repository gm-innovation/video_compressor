"""Runner dos testes do sistema: um `unittest` que chama os scripts `tests/test-*.py`.

Os testes do projeto são scripts (nome com hífen, não importáveis) que devolvem código de saída 0 quando
passam. Aqui eles entram num runner de verdade, para que "os testes passaram" seja um fato verificável
(`python -m unittest`), e não a leitura de um print solto.

    python -m unittest discover -s tests -p 'suite.py' -t .
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TESTES = sorted(p for p in (RAIZ / "tests").glob("test-*.py") if p.is_file())


class TestesDoSistema(unittest.TestCase):
    """Cada script `tests/test-*.py` tem de sair com código 0."""

    @unittest.skipIf(not TESTES, "nenhum script tests/test-*.py encontrado")
    def test_scripts_do_projeto(self) -> None:
        for script in TESTES:
            with self.subTest(script=script.name):
                proc = subprocess.run(
                    [sys.executable, str(script)],
                    cwd=str(RAIZ), capture_output=True, text=True, timeout=300,
                )
                self.assertEqual(
                    proc.returncode, 0,
                    f"{script.name} saiu com {proc.returncode}\n"
                    f"--- saida:\n{proc.stdout[-1500:]}\n--- erro:\n{proc.stderr[-1500:]}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)

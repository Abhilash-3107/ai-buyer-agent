"""The import-layer contract in pyproject.toml (import-linter) must hold."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def test_import_layers_are_respected():
    cmd = [sys.executable, "-c", "from importlinter.cli import lint_imports_command as main; main()"]
    proc = subprocess.run(cmd, check=False, cwd=BACKEND, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr

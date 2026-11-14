"""Shared fixtures."""
from dataclasses import replace

import pytest

from app import config


@pytest.fixture
def use_settings(tmp_path, monkeypatch):
    """Point the app's settings at tmp_path (runs in tmp_path/runs, evals in tmp_path/eval); keywords override fields."""
    def apply(**overrides) -> config.Settings:
        base = config.Settings(data_dir=tmp_path, runs_dir=tmp_path / "runs", eval_dir=tmp_path / "eval",
                               frontend_dist=tmp_path / "dist")
        settings = replace(base, **overrides)
        monkeypatch.setattr(config, "_settings", settings)
        return settings
    return apply

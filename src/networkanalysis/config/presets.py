"""Load and save :class:`GenConfig` presets as YAML under ``config/presets/``.

Five presets ship with the project (see ``config/presets/*.yaml``). Users can save their
own from the dashboard Settings page; those land in the same directory.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from networkanalysis.config.models import GenConfig
from networkanalysis.paths import PRESETS_DIR

BUILTIN = (
    "healthy_week",
    "monsoon",
    "congestion_buildup",
    "fiber_cut_cluster",
    "mixed_realistic",
)


def builtin_preset_names() -> list[str]:
    return list(BUILTIN)


def preset_path(name: str) -> Path:
    return PRESETS_DIR / f"{name}.yaml"


def list_presets() -> list[str]:
    if not PRESETS_DIR.exists():
        return builtin_preset_names()
    found = sorted(p.stem for p in PRESETS_DIR.glob("*.yaml"))
    return found or builtin_preset_names()


def load_preset(name: str) -> GenConfig:
    path = preset_path(name)
    if not path.exists():
        raise FileNotFoundError(f"preset {name!r} not found at {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return GenConfig.model_validate(raw)


def load_config(source: str | Path) -> GenConfig:
    """Load from a preset name or a path to a YAML file."""
    p = Path(source)
    if p.exists():
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return GenConfig.model_validate(raw)
    return load_preset(str(source))


def save_preset(cfg: GenConfig, name: str | None = None) -> Path:
    name = name or cfg.name
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    path = preset_path(name)
    path.write_text(
        yaml.safe_dump(cfg.to_yaml_dict(), sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return path

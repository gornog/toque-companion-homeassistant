"""Validate manifest, hacs.json, translations parity, and brand assets."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMP = ROOT / "custom_components" / "toque_companion"


def _flatten_keys(obj: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for k, v in obj.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= _flatten_keys(v, path)
        else:
            keys.add(path)
    return keys


def test_hacs_json_valid() -> None:
    data = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert data["name"] == "Toque Companion"
    assert "homeassistant" in data


def test_manifest_hassfest_ordering_and_fields() -> None:
    manifest = json.loads((COMP / "manifest.json").read_text(encoding="utf-8"))
    keys = list(manifest.keys())
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:]), "manifest.json keys after domain/name must be sorted"
    assert manifest["domain"] == "toque_companion"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_push"
    assert manifest["requirements"] == []
    assert manifest["codeowners"] == ["@gornog"]


def test_translations_parity() -> None:
    strings = json.loads((COMP / "strings.json").read_text(encoding="utf-8"))
    en = json.loads((COMP / "translations" / "en.json").read_text(encoding="utf-8"))
    fr = json.loads((COMP / "translations" / "fr.json").read_text(encoding="utf-8"))

    assert strings == en, "strings.json and translations/en.json must stay identical"
    assert _flatten_keys(strings) == _flatten_keys(fr), "fr.json keys must match strings.json"


def test_brand_assets_present() -> None:
    brand = COMP / "brand"
    for name in ("icon.png", "icon@2x.png", "logo.png", "logo@2x.png", "dark_logo.png", "dark_logo@2x.png"):
        path = brand / name
        assert path.is_file() and path.stat().st_size > 100

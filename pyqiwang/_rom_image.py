"""Verified loading and local extraction of the Qi Wang runtime PRG image."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

_MANIFEST_PATH = Path(__file__).with_name("rom_manifest.json")


class RomImageError(ValueError):
    """Raised when a ROM image is unsupported, modified, or malformed."""


def load_manifest() -> dict[str, Any]:
    with _MANIFEST_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verified_source_prg(data: bytes, manifest: dict[str, Any]) -> bytes:
    source = manifest["source"]
    digest = sha256_bytes(data)
    if len(data) != source["size"] or digest != source["sha256"]:
        raise RomImageError(
            "Unknown or modified Qi Wang ROM image: "
            f"size={len(data)}, sha256={digest}. "
            f"Expected size={source['size']}, sha256={source['sha256']}."
        )
    if data[:16].hex() != source["header_hex"]:
        raise RomImageError("The iNES header does not match the known-good image.")
    prg_size = source["prg_banks"] * 0x4000
    prg = data[16:16 + prg_size]
    _verify_runtime_prg(prg, manifest)
    return prg


def _verify_runtime_prg(data: bytes, manifest: dict[str, Any]) -> None:
    runtime = manifest["runtime"]
    digest = sha256_bytes(data)
    if len(data) != runtime["size"] or digest != runtime["sha256"]:
        raise RomImageError(
            "Unknown or modified Qi Wang runtime image: "
            f"size={len(data)}, sha256={digest}. "
            f"Expected size={runtime['size']}, sha256={runtime['sha256']}."
        )


def load_verified_prg(path: str | os.PathLike[str]) -> bytes:
    """Load a known-good full iNES image or locally extracted 64KB PRG."""
    image_path = Path(path)
    data = image_path.read_bytes()
    manifest = load_manifest()
    if data.startswith(b"NES\x1a"):
        return _verified_source_prg(data, manifest)
    _verify_runtime_prg(data, manifest)
    return data


def extract_verified_prg(
    source_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
) -> Path:
    """Verify a known source ROM and write its 64KB runtime PRG locally."""
    source = Path(source_path)
    output = Path(output_path)
    prg = _verified_source_prg(source.read_bytes(), load_manifest())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(prg)
    return output


def configured_image_path() -> Path | None:
    """Return the explicit image path configured through the environment."""
    env_path = os.environ.get("PYQIWANG_ROM_IMAGE")
    return Path(env_path).expanduser() if env_path else None


def default_image_candidates() -> list[Path]:
    """Return runtime-image candidates in deterministic preference order."""
    package_dir = Path(__file__).resolve().parent
    root = package_dir.parent
    candidates = []
    configured = configured_image_path()
    if configured is not None:
        candidates.append(configured)
    candidates.extend([
        package_dir / "qiwang.prg",
        root / "qiwang.prg",
        package_dir / "棋王(繁)[小天才](CN)[TAB](0.75Mb).nes",
        root / "棋王(繁)[小天才](CN)[TAB](0.75Mb).nes",
    ])
    return candidates


def find_default_image() -> Path | None:
    return next((path for path in default_image_candidates() if path.is_file()), None)

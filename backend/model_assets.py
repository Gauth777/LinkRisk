"""Deployment helper for the git-ignored frozen model bundle."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from urllib.request import urlopen
import zipfile


REQUIRED_ASSETS = (
    "artifacts/models/baseline_preprocessor.joblib",
    "artifacts/models/baseline_xgboost.joblib",
    "artifacts/models/feedback_specialist_v5.joblib",
    "artifacts/models/mentalist_v7_candidate.joblib",
    "artifacts/results/baseline_features.json",
    "artifacts/results/mentalist_v7_validation.json",
    "artifacts/results/mentalist_runtime_policy.json",
)


def asset_status(root: str | Path) -> dict:
    root_path = Path(root)
    missing = [item for item in REQUIRED_ASSETS if not (root_path / item).exists()]
    return {"ready": not missing, "missing": missing}


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if destination not in target.parents and target != destination:
            raise RuntimeError(f"Unsafe path in model bundle: {member.filename}")
    archive.extractall(destination)


def ensure_model_assets(root: str | Path) -> None:
    root_path = Path(root)
    status = asset_status(root_path)
    if status["ready"]:
        return

    url = os.getenv("LINKRISK_MODEL_BUNDLE_URL", "").strip()
    if not url:
        raise FileNotFoundError(
            "Missing frozen model assets: " + ", ".join(status["missing"])
        )

    expected_sha = os.getenv("LINKRISK_MODEL_BUNDLE_SHA256", "").strip().lower()
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
        temp_path = Path(handle.name)
        with urlopen(url, timeout=120) as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)

    try:
        if expected_sha:
            digest = hashlib.sha256(temp_path.read_bytes()).hexdigest()
            if digest.lower() != expected_sha:
                raise RuntimeError(
                    f"Model bundle SHA256 mismatch: expected {expected_sha}, got {digest}"
                )
        with zipfile.ZipFile(temp_path) as archive:
            _safe_extract(archive, root_path)
    finally:
        temp_path.unlink(missing_ok=True)

    final = asset_status(root_path)
    if not final["ready"]:
        raise FileNotFoundError(
            "Downloaded model bundle is incomplete: " + ", ".join(final["missing"])
        )

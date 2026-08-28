from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "find_focused_review_candidate.py"


def _module():
    spec = importlib.util.spec_from_file_location("focused_review", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_focused_rows_keep_public_inputs_fixed_and_vary_profile() -> None:
    module = _module()
    frame, profiles = module._rows(0, 2, amount=499.0)

    assert profiles == ["REVIEW-F-0000000", "REVIEW-F-0000001"]
    assert frame["TransactionAmt"].tolist() == [499.0, 499.0]
    assert frame["ProductCD"].tolist() == ["H", "H"]
    assert frame["DeviceInfo"].tolist() == ["rv:52.0", "rv:52.0"]
    assert frame["id_31"].tolist() == ["safari generic", "safari generic"]
    assert frame["R_emaildomain"].tolist() == ["gmail.com", "gmail.com"]
    assert frame["card4"].tolist() == ["netbanking", "netbanking"]
    assert frame["card6"].tolist() == ["unknown", "unknown"]
    assert frame["card1"].iloc[0] != frame["card1"].iloc[1]

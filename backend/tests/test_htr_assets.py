from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ai_engine.htr.reference.page import DEFAULT_DET


def test_bundled_htr_configuration_matches_expected_model_dimensions():
    root = Path(__file__).resolve().parents[2]
    config_path = root / "ai_engine" / "htr" / "models" / "ar.json"
    model_path = root / "ai_engine" / "htr" / "models" / "ar.onnx"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert len(config["charset"]) == 50
    assert config["height"] == 64
    assert config["downsample"] == 4
    assert config["script"] == "arabic"
    assert config["rtl"] is True
    assert model_path.is_file()
    assert len(hashlib.sha256(model_path.read_bytes()).hexdigest()) == 64


def test_default_text_detector_path_points_to_bundled_detector():
    assert DEFAULT_DET.is_file()
    assert DEFAULT_DET.name == "ppocr_det_v4.onnx"
    assert DEFAULT_DET.parent.name == "models"

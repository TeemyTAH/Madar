from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from ai_engine.htr.engine import ArabicHTREngine
from ai_engine.htr.reference.charset import Charset


class FakeSession:
    def __init__(self):
        # CTC classes: blank=0, alef=1, beh=2. The most likely text is alef.
        self.logits = np.asarray(
            [[
                [-2.0, 8.0, -2.0],
                [8.0, -2.0, -2.0],
                [8.0, -2.0, -2.0],
            ]],
            dtype=np.float32,
        )

    def run(self, output_names, inputs):
        assert output_names == ["logits"]
        tensor = inputs["image"]
        assert tensor.ndim == 4 and tensor.shape[1] == 1
        return [self.logits]


def fake_engine() -> ArabicHTREngine:
    engine = ArabicHTREngine.__new__(ArabicHTREngine)
    engine.charset_text = "اب"
    engine.charset = Charset("اب")
    engine.height = 64
    engine.downsample = 4
    engine.script = "latin"
    engine.rtl = False
    engine.input_name = "image"
    engine.output_name = "logits"
    engine.session = FakeSession()
    engine.beam_size = 8
    engine.review_threshold = 0.0
    engine.model_version = "test-model"
    engine._detector = object()
    engine.detector_path = Path("fake-detector.onnx")
    return engine


def test_preprocess_line_returns_valid_ctc_tensor():
    engine = fake_engine()
    image = Image.new("RGB", (200, 50), "white")
    tensor = engine.preprocess_line(image)
    assert tensor.shape == (1, 1, 64, 256)
    assert tensor.dtype == np.float32
    assert tensor.min() >= 0.0 and tensor.max() <= 1.0


def test_greedy_decoder_collapses_ctc_repeats_and_blanks():
    engine = fake_engine()
    logits = np.asarray([[0, 8, 0], [8, 0, 0], [8, 0, 0]], dtype=np.float32)
    assert engine.decode(logits) == "ا"


def test_arabic_output_order_uses_reference_rtl_conversion():
    engine = fake_engine()
    engine.script = "arabic"
    assert engine.restore_text_order("cba 321") == "abc 123"


def test_recognize_line_uses_beam_decoder_and_returns_review_metadata():
    engine = fake_engine()
    result = engine.recognize_line(Image.new("L", (180, 50), 255))
    assert result["text"] == "ا"
    assert result["decoder"] == "ctc_prefix_beam_search"
    assert 0 <= result["confidence"] <= 1
    assert result["needs_review"] is False
    assert result["classes"] == 3
    assert result["input_shape"] == [1, 1, 64, 232]


def test_page_recognition_detects_lines_and_returns_page_metadata(tmp_path, monkeypatch):
    import ai_engine.htr.reference.page as page_module

    engine = fake_engine()
    image_path = tmp_path / "page.png"
    Image.new("RGB", (400, 300), "white").save(image_path)
    fake_line = SimpleNamespace(
        image=np.full((40, 180), 255, dtype=np.uint8),
        box=(20, 30, 200, 70),
        angle=0.5,
    )
    monkeypatch.setattr(page_module, "segment_page", lambda *args, **kwargs: [fake_line])
    result = engine.recognize_page(image_path)
    assert result["line_count"] == 1
    assert result["text"] == "ا"
    assert result["segmentation_method"] == "dbnet"
    assert result["lines"][0]["box"] == [20, 30, 200, 70]


def test_page_recognition_returns_review_when_no_lines_are_detected(tmp_path, monkeypatch):
    import ai_engine.htr.reference.page as page_module

    engine = fake_engine()
    image_path = tmp_path / "blank.png"
    Image.new("RGB", (300, 300), "white").save(image_path)
    monkeypatch.setattr(page_module, "segment_page", lambda *args, **kwargs: [])
    result = engine.recognize_page(image_path)
    assert result["line_count"] == 0
    assert result["needs_review"] is True
    assert result["status"] == "REQUIRES_REVIEW"

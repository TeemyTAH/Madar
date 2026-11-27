from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from .reference.charset import Charset
from .reference.decode import beam_search
from .reference.text import from_output


class HTRConfigurationError(RuntimeError):
    """Raised when the Arabic HTR model/configuration is inconsistent."""


class ArabicHTREngine:
    """Arabic line/page recognizer backed by the bundled ONNX CTC model.

    The bundled recognizer is a baseline model, not a newly trained Madar model.
    Its beam confidence is a search-posterior indicator and must not be interpreted
    as calibrated character accuracy. Low-confidence output is therefore routed to
    teacher review by default.
    """

    MODEL_NAME = "ArabicHTR-CTC-ONNX"

    def __init__(
        self,
        model_path: str | Path | None = None,
        config_path: str | Path | None = None,
        detector_path: str | Path | None = None,
        threads: int = 1,
        beam_size: int = 16,
        review_threshold: float = 0.60,
    ) -> None:
        model_dir = Path(__file__).resolve().parent / "models"
        self.model_path = Path(model_path or model_dir / "ar.onnx").expanduser().resolve()
        self.config_path = Path(config_path or model_dir / "ar.json").expanduser().resolve()
        self.detector_path = Path(detector_path or model_dir / "ppocr_det_v4.onnx").expanduser().resolve()

        if not self.model_path.is_file():
            raise FileNotFoundError(f"Arabic HTR model not found: {self.model_path}")
        if not self.config_path.is_file():
            raise FileNotFoundError(f"Arabic HTR configuration not found: {self.config_path}")
        if not 0.0 <= float(review_threshold) <= 1.0:
            raise ValueError("review_threshold must be between 0 and 1")

        try:
            self.meta = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            self.charset_text = str(self.meta["charset"])
            self.height = int(self.meta["height"])
            self.downsample = int(self.meta["downsample"])
            self.script = str(self.meta["script"])
            rtl_value = self.meta["rtl"]
            if not isinstance(rtl_value, bool):
                raise TypeError("rtl must be a JSON boolean")
            self.rtl = rtl_value
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HTRConfigurationError(f"Invalid HTR model configuration: {exc}") from exc

        if not self.charset_text or len(set(self.charset_text)) != len(self.charset_text):
            raise HTRConfigurationError("HTR charset is empty or contains duplicate characters")
        if self.height != 64 or self.downsample <= 0:
            raise HTRConfigurationError("Unsupported HTR image height/downsample configuration")
        if self.script != "arabic" or not self.rtl:
            raise HTRConfigurationError("The bundled model configuration must be Arabic RTL")

        try:
            import onnxruntime as ort
        except ImportError as exc:  # lazy import keeps non-AI API tools importable
            raise RuntimeError("onnxruntime is required for Arabic HTR inference") from exc

        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, int(threads))
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(self.model_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        if len(inputs) != 1 or len(outputs) != 1:
            raise HTRConfigurationError("Expected one input and one output tensor")
        input_meta, output_meta = inputs[0], outputs[0]
        if len(input_meta.shape) != 4 or input_meta.shape[1] != 1 or input_meta.shape[2] != self.height:
            raise HTRConfigurationError(f"Unexpected HTR input tensor shape: {input_meta.shape}")
        if output_meta.shape[-1] != len(self.charset_text) + 1:
            raise HTRConfigurationError(
                "Model output classes do not match charset length plus CTC blank"
            )

        self.input_name = input_meta.name
        self.output_name = output_meta.name
        self.charset = Charset(self.charset_text)
        self.providers = self.session.get_providers()
        self.beam_size = max(1, min(int(beam_size), 64))
        self.review_threshold = float(review_threshold)
        self.model_version = hashlib.sha256(self.model_path.read_bytes()).hexdigest()[:16]
        self._detector: Any | None = None

    def preprocess_line(self, source: str | Path | Image.Image) -> np.ndarray:
        """Match the reference preprocessing exactly: grayscale, autocontrast, resize, RTL mirror, pad."""
        if isinstance(source, Image.Image):
            image = source.copy()
        else:
            with Image.open(source) as opened:
                image = ImageOps.exif_transpose(opened).copy()

        image = ImageOps.autocontrast(image.convert("L"), cutoff=1)
        width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError("Invalid line image dimensions")

        new_width = max(self.downsample * 4, round(width * self.height / height))
        new_width = min(new_width, 2048)
        image = image.resize((new_width, self.height), Image.Resampling.BILINEAR)
        array = 1.0 - np.asarray(image, dtype=np.float32) / 255.0
        if self.rtl:
            array = np.ascontiguousarray(array[:, ::-1])

        padded_width = ((new_width + self.downsample - 1) // self.downsample) * self.downsample
        if padded_width != new_width:
            array = np.pad(array, ((0, 0), (0, padded_width - new_width)), mode="constant")
        return np.ascontiguousarray(array[None, None, :, :], dtype=np.float32)

    def _run_logits(self, tensor: np.ndarray) -> np.ndarray:
        output = self.session.run([self.output_name], {self.input_name: tensor})[0]
        if output.ndim != 3 or output.shape[0] != 1:
            raise HTRConfigurationError(f"Unexpected HTR output shape: {output.shape}")
        if output.shape[-1] != self.charset.num_classes:
            raise HTRConfigurationError("Runtime output class count does not match configured charset")
        return output[0]

    def decode(self, logits: np.ndarray) -> str:
        """CTC greedy decoder retained for baseline comparison and compatibility."""
        ids = np.argmax(logits, axis=-1)
        return self.charset.decode_greedy(ids)

    def restore_text_order(self, text: str) -> str:
        return from_output(text, self.script)

    def recognize_line(self, source: str | Path | Image.Image, beam_size: int | None = None) -> dict[str, Any]:
        total_start = time.perf_counter()
        prep_start = time.perf_counter()
        tensor = self.preprocess_line(source)
        prep_ms = (time.perf_counter() - prep_start) * 1000

        inference_start = time.perf_counter()
        logits = self._run_logits(tensor)
        inference_ms = (time.perf_counter() - inference_start) * 1000

        decode_start = time.perf_counter()
        decoded = beam_search(
            logits,
            self.charset,
            beam=max(1, min(int(beam_size or self.beam_size), 64)),
        )
        text = self.restore_text_order(decoded.text).strip()
        alternatives = [
            {"text": self.restore_text_order(candidate).strip(), "posterior": round(float(score), 6)}
            for candidate, score in decoded.alternatives[:5]
        ]
        decode_ms = (time.perf_counter() - decode_start) * 1000
        total_ms = (time.perf_counter() - total_start) * 1000
        confidence = max(0.0, min(1.0, float(decoded.confidence)))
        needs_review = (not text) or (not decoded.valid) or confidence < self.review_threshold

        return {
            "text": text,
            "raw_text": decoded.text,
            "confidence": round(confidence, 6),
            "confidence_percent": round(confidence * 100, 2),
            "needs_review": bool(needs_review),
            "decoder": "ctc_prefix_beam_search",
            "beam_size": max(1, min(int(beam_size or self.beam_size), 64)),
            "alternatives": alternatives,
            "preprocessing_ms": round(prep_ms, 2),
            "inference_ms": round(inference_ms, 2),
            "decoding_ms": round(decode_ms, 2),
            "total_ms": round(total_ms, 2),
            "frames": int(logits.shape[0]),
            "classes": int(logits.shape[1]),
            "input_shape": list(tensor.shape),
            "model_name": self.MODEL_NAME,
            "model_version": self.model_version,
        }

    def _get_detector(self):
        if self._detector is None:
            if not self.detector_path.is_file():
                raise FileNotFoundError(f"Arabic text detector not found: {self.detector_path}")
            from .reference.page import TextDetector
            self._detector = TextDetector(path=self.detector_path)
        return self._detector

    @staticmethod
    def _load_page(source: str | Path | Image.Image) -> np.ndarray:
        import cv2
        if isinstance(source, Image.Image):
            image = ImageOps.exif_transpose(source).convert("RGB")
        else:
            with Image.open(source) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
        rgb = np.asarray(image, dtype=np.uint8)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    def recognize_page(
        self,
        source: str | Path | Image.Image,
        beam_size: int | None = None,
        paper: bool = True,
        use_detector: bool = True,
    ) -> dict[str, Any]:
        """Detect handwriting lines on a page, recognize them in Arabic reading order."""
        total_start = time.perf_counter()
        page = self._load_page(source)
        from .reference.page import segment_page

        lines = []
        segmentation_method = "dbnet"
        if use_detector:
            lines = segment_page(
                page, method="db", rtl=self.rtl, paper=paper, det=self._get_detector()
            )
        if not lines:
            segmentation_method = "blobs_fallback"
            lines = segment_page(page, method="blobs", rtl=self.rtl, paper=paper)
        if not lines:
            segmentation_method = "projection_fallback"
            lines = segment_page(page, method="projection", rtl=self.rtl, paper=paper)

        recognized: list[dict[str, Any]] = []
        for index, line in enumerate(lines, start=1):
            line_image = Image.fromarray(line.image)
            result = self.recognize_line(line_image, beam_size=beam_size)
            recognized.append({
                "line_number": index,
                "text": result["text"],
                "confidence": result["confidence"],
                "confidence_percent": result["confidence_percent"],
                "needs_review": result["needs_review"],
                "box": [int(v) for v in line.box],
                "angle_degrees": round(float(line.angle), 3),
                "alternatives": result["alternatives"],
                "timing_ms": {
                    "preprocessing": result["preprocessing_ms"],
                    "inference": result["inference_ms"],
                    "decoding": result["decoding_ms"],
                    "total": result["total_ms"],
                },
            })

        full_text = "\n".join(item["text"] for item in recognized if item["text"])
        confidences = [item["confidence"] for item in recognized]
        confidence = min(confidences) if confidences else 0.0
        needs_review = (not recognized) or any(item["needs_review"] for item in recognized)
        return {
            "text": full_text,
            "lines": recognized,
            "line_count": len(recognized),
            "confidence": round(confidence, 6),
            "confidence_percent": round(confidence * 100, 2),
            "needs_review": bool(needs_review),
            "status": "REQUIRES_REVIEW" if needs_review else "SUCCEEDED",
            "segmentation_method": segmentation_method,
            "model_name": self.MODEL_NAME,
            "model_version": self.model_version,
            "detector_name": "PP-OCRv4-DBNet" if segmentation_method == "dbnet" else None,
            "total_ms": round((time.perf_counter() - total_start) * 1000, 2),
            "confidence_note": "Beam posterior is an uncalibrated hypothesis score, not a validated accuracy probability.",
        }

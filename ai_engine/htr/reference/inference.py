"""Lightweight ONNX Runtime recognizer (numpy + PIL + onnxruntime, no torch)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from .charset import Charset
from .decode import Decoded, beam_search
from .preprocess import pad_width, preprocess
from .text import from_output


class OnnxRecognizer:
    def __init__(self, path: str | Path, threads: int = 1):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        meta = self.session.get_modelmeta().custom_metadata_map
        self.charset = Charset(meta["charset"])
        self.height = int(meta.get("height", 64))
        self.script = meta.get("script", "latin")
        self.rtl = meta.get("rtl", "0") == "1"
        self.input_name = self.session.get_inputs()[0].name

    def prepare(self, img: Image.Image) -> np.ndarray:
        return pad_width(preprocess(img, self.height, rtl=self.rtl))[None, None]

    def logits(self, x: np.ndarray) -> np.ndarray:
        """(T, C) logits for one prepared line."""
        return self.session.run(None, {self.input_name: x})[0][0]

    def run(self, x: np.ndarray) -> str:
        return from_output(self.charset.decode_greedy(self.logits(x).argmax(-1)), self.script)

    def __call__(self, img: Image.Image) -> str:
        return self.run(self.prepare(img))

    def read(self, img: Image.Image, constraint=None, beam: int = 16, lm=None) -> Decoded:
        """Beam-search decode with confidence; `constraint` restricts the output (see htr.fields),
        `lm` (htr.lm.LMScorer) adds a language model."""
        d = beam_search(self.logits(self.prepare(img)), self.charset, beam=beam, constraint=constraint, lm=lm)
        return Decoded(from_output(d.text, self.script), d.confidence, d.valid,
                       [(from_output(t, self.script), q) for t, q in d.alternatives])

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import pytest

from ai_engine.image_processing.processor import ImageProcessor, ImageProcessingError


def test_processor_creates_original_and_processed_files_after_processing(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (1200, 1200), (245, 245, 245)).save(source)
    processor = ImageProcessor(project_root=tmp_path)
    result = processor.process_image(source)
    assert (tmp_path / result.original_path).is_file()
    assert (tmp_path / result.processed_path).is_file()
    assert result.image_width == 1200
    assert result.image_height == 1200


def test_processor_removes_partial_outputs_if_original_copy_fails(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (1200, 1200), (245, 245, 245)).save(source)
    processor = ImageProcessor(project_root=tmp_path)
    with patch("ai_engine.image_processing.processor.shutil.copy2", side_effect=OSError("simulated copy failure")):
        with pytest.raises(ImageProcessingError):
            processor.process_image(source)
    assert list(processor.original_dir.iterdir()) == []
    assert list(processor.processed_dir.iterdir()) == []


def test_processor_rejects_invalid_image_without_creating_outputs(tmp_path):
    source = tmp_path / "invalid.png"
    source.write_bytes(b"not an image")
    processor = ImageProcessor(project_root=tmp_path)
    with pytest.raises(ImageProcessingError):
        processor.process_image(source)
    assert list(processor.original_dir.iterdir()) == []
    assert list(processor.processed_dir.iterdir()) == []

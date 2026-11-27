from __future__ import annotations

import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


QualityStatus = Literal["VALID", "LOW_QUALITY", "INVALID"]


class ImageProcessingError(Exception):
    """Raised when an input image cannot be processed safely."""


@dataclass(frozen=True)
class ImageProcessingResult:
    original_path: str
    processed_path: str
    quality_status: QualityStatus
    image_width: int
    image_height: int
    blur_score: float
    brightness: float
    contrast: float
    skew_angle_degrees: float
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


class ImageProcessor:
    """Prepare student answer-sheet images for Arabic handwriting recognition."""

    ALLOWED_EXTENSIONS = {
        ".jpg", ".jpeg", ".png", ".bmp",
        ".tif", ".tiff", ".webp"
    }

    def __init__(
        self,
        project_root: str | Path | None = None,
        max_file_size_mb: float = 20.0,
        max_dimension: int = 12000,
        min_short_side: int = 900,
        blur_threshold: float = 35.0,
        max_deskew_angle: float = 7.0,
    ) -> None:

        self.project_root = (
            Path(project_root).expanduser().resolve()
            if project_root is not None
            else Path(__file__).resolve().parents[2]
        )

        self.storage_dir = self.project_root / "storage"
        self.original_dir = self.storage_dir / "original_images"
        self.processed_dir = self.storage_dir / "processed_images"

        self.max_file_size_bytes = int(max_file_size_mb * 1024 * 1024)
        self.max_dimension = max_dimension
        self.min_short_side = min_short_side
        self.blur_threshold = blur_threshold
        self.max_deskew_angle = max_deskew_angle

        self.original_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _estimate_skew(gray: np.ndarray) -> float:
        """Estimate document rotation using foreground pixels."""

        _, binary = cv2.threshold(
            gray,
            0,
            255,
            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
        )

        points = np.column_stack(np.where(binary > 0))

        if len(points) < 100:
            return 0.0

        # Limit the number of points to reduce CPU and memory usage.
        if len(points) > 250000:
            step = max(1, len(points) // 250000)
            points = points[::step]

        angle = cv2.minAreaRect(
            points.astype(np.float32)
        )[-1]

        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        return float(angle)

    @staticmethod
    def _rotate(gray: np.ndarray, angle: float) -> np.ndarray:
        """Rotate the image while preserving its original dimensions."""

        height, width = gray.shape

        center = (width / 2, height / 2)

        matrix = cv2.getRotationMatrix2D(
            center,
            angle,
            1.0,
        )

        return cv2.warpAffine(
            gray,
            matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=255,
        )

    def process_image(
        self,
        source: str | Path,
    ) -> ImageProcessingResult:
        """Validate, preprocess and save an answer-sheet image."""

        source_path = Path(source).expanduser().resolve()

        if not source_path.is_file():
            raise ImageProcessingError(
                f"Image file does not exist: {source_path}"
            )

        if source_path.suffix.lower() not in self.ALLOWED_EXTENSIONS:
            raise ImageProcessingError(
                "Unsupported image format."
            )

        file_size = source_path.stat().st_size

        if file_size == 0:
            raise ImageProcessingError("Image file is empty.")

        if file_size > self.max_file_size_bytes:
            raise ImageProcessingError(
                "Image exceeds the configured file-size limit."
            )

        try:
            with Image.open(source_path) as img:
                img.verify()

            with Image.open(source_path) as img:
                img = ImageOps.exif_transpose(img)

                width, height = img.size

                if width > self.max_dimension or height > self.max_dimension:
                    raise ImageProcessingError(
                        "Image dimensions exceed the configured limit."
                    )

                if width < 300 or height < 300:
                    raise ImageProcessingError(
                        "Image resolution is too small to process reliably."
                    )

                img.load()

                if "A" in img.getbands() or "transparency" in img.info:
                    rgba = img.convert("RGBA")
                    background = Image.new(
                        "RGBA", rgba.size, (255, 255, 255, 255)
                    )
                    rgb_image = Image.alpha_composite(
                        background, rgba
                    ).convert("RGB")
                else:
                    rgb_image = img.convert("RGB")

        except ImageProcessingError:
            raise
        except (
            UnidentifiedImageError,
            OSError,
            Image.DecompressionBombError,
        ) as exc:
            raise ImageProcessingError(
                f"Cannot read image safely: {exc}"
            ) from exc

        image_id = uuid.uuid4().hex
        original_path = self.original_dir / (
            image_id + source_path.suffix.lower()
        )
        processed_path = self.processed_dir / (
            image_id + ".png"
        )

        # Process in memory first. Files are written only after every transformation
        # and quality calculation has succeeded, avoiding orphaned partial outputs.
        rgb_array = np.asarray(rgb_image)

        bgr = cv2.cvtColor(
            rgb_array,
            cv2.COLOR_RGB2BGR,
        )

        gray = cv2.cvtColor(
            bgr,
            cv2.COLOR_BGR2GRAY,
        )

        # Measure quality before enhancement.
        brightness = float(np.mean(gray))
        contrast = float(np.std(gray))
        blur_score = float(
            cv2.Laplacian(
                gray, cv2.CV_64F
            ).var()
        )

        warnings_list: list[str] = []

        # Estimate rotation and correct only safe angles.
        estimated_angle = self._estimate_skew(gray)

        applied_angle = 0.0

        if abs(estimated_angle) <= self.max_deskew_angle:
            if abs(estimated_angle) >= 0.3:
                gray = self._rotate(gray, estimated_angle)
                applied_angle = estimated_angle
        else:
            warnings_list.append(
                "Skew exceeds the safe automatic correction limit."
            )

        # Lightweight denoising and contrast enhancement.
        denoised = cv2.medianBlur(gray, 3)

        clahe = cv2.createCLAHE(
            clipLimit=2.0,
            tileGridSize=(8, 8),
        )

        enhanced = clahe.apply(denoised)

       
        # Encode the image in memory first.
        success, encoded_image = cv2.imencode(
            ".png",
            enhanced,
            [cv2.IMWRITE_PNG_COMPRESSION, 3],
        )

        if not success:
            raise ImageProcessingError(
                "Failed to encode the processed image."
            )

        # Initial quality rules; thresholds require dataset validation.
        if min(width, height) < self.min_short_side:
            warnings_list.append("Image resolution is relatively low.")

        if blur_score < self.blur_threshold:
            warnings_list.append("Image may be blurry.")

        if brightness < 40 or brightness > 225:
            warnings_list.append("Image brightness is outside the preferred range.")

        if contrast < 20:
            warnings_list.append("Image contrast is low.")

        quality_status: QualityStatus = (
            "LOW_QUALITY" if warnings_list else "VALID"
        )

        # Commit both generated files together from the processor's perspective.
        # If either write fails, remove both so the upload service never inherits
        # orphaned images without a corresponding database row.
        try:
            processed_path.write_bytes(encoded_image.tobytes())
            if not processed_path.is_file() or processed_path.stat().st_size == 0:
                raise OSError("Processed image was not saved correctly")
            shutil.copy2(source_path, original_path)
            if not original_path.is_file() or original_path.stat().st_size == 0:
                raise OSError("Original image was not preserved correctly")
        except OSError as exc:
            processed_path.unlink(missing_ok=True)
            original_path.unlink(missing_ok=True)
            raise ImageProcessingError(f"Failed to save processed/original images: {exc}") from exc

        return ImageProcessingResult(
            original_path=original_path.relative_to(
                self.project_root
            ).as_posix(),

            processed_path=processed_path.relative_to(
                self.project_root
            ).as_posix(),

            quality_status=quality_status,
            image_width=width,
            image_height=height,
            blur_score=round(blur_score, 2),
            brightness=round(brightness, 2),
            contrast=round(contrast, 2),
            skew_angle_degrees=round(applied_angle, 2),
            warnings=tuple(warnings_list),
        )

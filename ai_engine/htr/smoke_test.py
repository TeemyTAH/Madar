from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import ArabicHTREngine


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Madar Arabic HTR + page text detection")
    parser.add_argument(
        "image",
        nargs="?",
        default="docs/arabic_test_line.png",
        help="Page or line image to recognize (default: docs/arabic_test_line.png)",
    )
    args = parser.parse_args()
    image = Path(args.image).expanduser().resolve()
    if not image.is_file():
        parser.error(f"Image does not exist: {image}")

    engine = ArabicHTREngine()
    print("HTR MODEL:", engine.model_path)
    print("HTR VERSION:", engine.model_version)
    print("DETECTOR MODEL:", engine.detector_path)
    print("PROVIDERS:", engine.providers)
    result = engine.recognize_page(image)
    print("\n========== PAGE RECOGNITION ==========")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\nSMOKE TEST COMPLETED")
    print("REVIEW REQUIRED:", result["needs_review"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

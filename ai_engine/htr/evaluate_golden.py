from pathlib import Path
import csv
import json
import hashlib
import unicodedata
from datetime import datetime, timezone

from ai_engine.htr.engine import ArabicHTREngine


ROOT = Path("ai_engine/htr/dataset/golden_test")
MANIFEST = ROOT / "labels.csv"
OUTPUT = ROOT / "baseline_results.json"


def normalize(text):
    text = unicodedata.normalize("NFC", text)
    return " ".join(text.split())


def edit_distance(a, b):
    previous = list(range(len(b) + 1))

    for i, x in enumerate(a, 1):
        current = [i]

        for j, y in enumerate(b, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (x != y)
            ))

        previous = current

    return previous[-1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


with MANIFEST.open(encoding="utf-8-sig", newline="") as f:
    samples = list(csv.DictReader(f))

if not samples:
    raise RuntimeError("Golden dataset is empty.")

engine = ArabicHTREngine(threads=2)

model_hash = sha256(engine.model_path)

results = []

total_char_errors = 0
total_gt_chars = 0
total_word_errors = 0
total_gt_words = 0

print("========== MADAR BASELINE BENCHMARK ==========")
print("MODEL:", engine.model_path)
print("MODEL SHA256:", model_hash)
print("SAMPLES:", len(samples))

for sample in samples:

    image_path = ROOT / sample["image_path"]

    if not image_path.is_file():
        raise FileNotFoundError(image_path)

    image_hash = sha256(image_path)

    if image_hash != sample["sha256"]:
        raise RuntimeError(
            f"Image hash mismatch: {sample['sample_id']}"
        )

    expected = normalize(sample["ground_truth"])

    output = engine.recognize_line(image_path)
    predicted = normalize(output["text"])

    char_errors = edit_distance(
        list(predicted),
        list(expected)
    )

    word_errors = edit_distance(
        predicted.split(),
        expected.split()
    )

    gt_chars = len(expected)
    gt_words = len(expected.split())

    cer = char_errors / gt_chars if gt_chars else 0
    wer = word_errors / gt_words if gt_words else 0

    total_char_errors += char_errors
    total_gt_chars += gt_chars

    total_word_errors += word_errors
    total_gt_words += gt_words

    record = {
        "sample_id": sample["sample_id"],
        "ground_truth": expected,
        "prediction": predicted,
        "raw_prediction": output["raw_text"],
        "character_errors": char_errors,
        "ground_truth_characters": gt_chars,
        "CER": round(cer, 6),
        "word_errors": word_errors,
        "ground_truth_words": gt_words,
        "WER": round(wer, 6),
        "preprocessing_ms": output["preprocessing_ms"],
        "inference_ms": output["inference_ms"],
        "total_ms": output["total_ms"],
        "image_sha256": image_hash
    }

    results.append(record)

    print("\n" + "=" * 55)
    print("SAMPLE:", sample["sample_id"])
    print("EXPECTED:", ascii(expected))
    print("PREDICTED:", ascii(predicted))
    print("CHAR ERRORS:", char_errors, "/", gt_chars)
    print("CER:", f"{cer * 100:.2f}%")
    print("WORD ERRORS:", word_errors, "/", gt_words)
    print("WER:", f"{wer * 100:.2f}%")
    print("INFERENCE:", output["inference_ms"], "ms")
    print("TOTAL:", output["total_ms"], "ms")


aggregate_cer = (
    total_char_errors / total_gt_chars
    if total_gt_chars else 0
)

aggregate_wer = (
    total_word_errors / total_gt_words
    if total_gt_words else 0
)

report = {
    "benchmark": "MADAR_ARABIC_HTR_BASELINE",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "model_sha256": model_hash,
    "sample_count": len(results),
    "character_errors": total_char_errors,
    "ground_truth_characters": total_gt_chars,
    "aggregate_CER": aggregate_cer,
    "word_errors": total_word_errors,
    "ground_truth_words": total_gt_words,
    "aggregate_WER": aggregate_wer,
    "results": results
}

OUTPUT.write_text(
    json.dumps(report, ensure_ascii=True, indent=2),
    encoding="utf-8"
)

print("\n========== AGGREGATE RESULTS ==========")
print("CER:", f"{aggregate_cer * 100:.2f}%")
print("WER:", f"{aggregate_wer * 100:.2f}%")
print("SAMPLES:", len(results))
print("REPORT:", OUTPUT.resolve())
print("\nBASELINE BENCHMARK COMPLETED")

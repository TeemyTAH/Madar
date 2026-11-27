import csv
import json
from pathlib import Path
from PIL import Image
from ai_engine.htr.reference.inference import OnnxRecognizer

ROOT = Path("ai_engine/htr/dataset/golden_test")

with (ROOT / "labels.csv").open(
    encoding="utf-8-sig", newline=""
) as f:
    samples = list(csv.DictReader(f))

recognizer = OnnxRecognizer(
    Path("ai_engine/htr/models/ar.onnx"),
    threads=2
)

def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j-1] + (x != y)
            ))
        previous = current
    return previous[-1]

results = []

for sample in samples:
    path = ROOT / sample["image_path"]

    with Image.open(path) as image:
        image = image.convert("RGB")
        greedy = recognizer.run(recognizer.prepare(image))
        beam = recognizer.read(image, beam=16)

    expected = " ".join(sample["ground_truth"].split())

    record = {"sample_id": sample["sample_id"],
              "expected": expected}

    for name, prediction in [
        ("GREEDY", greedy),
        ("BEAM", beam.text)
    ]:
        prediction = " ".join(prediction.split())

        ce = distance(list(prediction), list(expected))
        we = distance(prediction.split(), expected.split())

        record[name] = {
            "prediction": prediction,
            "CER": round(100 * ce / len(expected), 2),
            "WER": round(100 * we / len(expected.split()), 2)
        }

    record["beam_confidence"] = beam.confidence
    record["beam_valid"] = beam.valid
    results.append(record)

    print("\nSAMPLE:", sample["sample_id"])
    print("EXPECTED:", ascii(expected))
    print("GREEDY:", ascii(greedy))
    print("GREEDY CER:", record["GREEDY"]["CER"], "%")
    print("BEAM:", ascii(beam.text))
    print("BEAM CER:", record["BEAM"]["CER"], "%")
    print("BEAM WER:", record["BEAM"]["WER"], "%")
    print("CONFIDENCE:", beam.confidence)

output = ROOT / "decoder_comparison.json"
output.write_text(
    json.dumps(results, ensure_ascii=True, indent=2),
    encoding="utf-8"
)

print("\nCOMPARISON FILE CREATED:", output.resolve())
print("SAMPLES TESTED:", len(results))

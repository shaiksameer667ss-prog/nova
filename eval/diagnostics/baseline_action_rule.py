import csv
from collections import defaultdict
from pathlib import Path

DATASET = Path("eval/results/qwen35_model_comparison_40_runs_20261109.csv")


def main():
    if not DATASET.is_file():
        raise FileNotFoundError(DATASET)

    groups = defaultdict(lambda: [0, 0])
    tp = tn = fp = fn = 0

    with DATASET.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise ValueError("Dataset is empty.")

    for row in rows:
        actions = [
            item.strip().split("[", 1)[0].strip()
            for item in row["ActionSequence"].split("->")
        ]

        if "done" not in actions:
            raise ValueError(f"Missing done action: {row['RunId']}")

        done_index = actions.index("done")
        predicted = "write_file" in actions[:done_index]

        label = row["VerifiedSuccess"].strip().lower()
        if label not in {"true", "false"}:
            raise ValueError(f"Invalid verification label: {label!r}")

        actual = label == "true"

        if predicted and actual:
            tp += 1
        elif not predicted and not actual:
            tn += 1
        elif predicted:
            fp += 1
        else:
            fn += 1

        key = (row["Task"], row["Model"])
        groups[key][1] += 1
        groups[key][0] += predicted == actual

    total = len(rows)
    accuracy = (tp + tn) / total
    sensitivity = tp / (tp + fn) if tp + fn else 0
    specificity = tn / (tn + fp) if tn + fp else 0

    print("WRITE-BEFORE-DONE BASELINE")
    print(f"Dataset records: {total}")
    print("\nPer task and model:")
    for key, (correct, count) in sorted(groups.items()):
        print(f"{key[0]:18} {key[1]:12} {correct}/{count}")

    print("\nConfusion matrix:")
    print(f"TP={tp} TN={tn} FP={fp} FN={fn}")
    print(f"Accuracy:          {accuracy:.1%}")
    print(f"Balanced accuracy: {(sensitivity + specificity) / 2:.1%}")


if __name__ == "__main__":
    main()

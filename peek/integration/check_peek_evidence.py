"""Summarize PEEK runtime evidence without requiring a GPU."""

import argparse
import glob
import json
from pathlib import Path


def load_json_files(pattern):
    records = []
    for filename in sorted(glob.glob(pattern)):
        try:
            with open(filename) as f:
                records.append((filename, json.load(f)))
        except (OSError, ValueError) as e:
            print(f"WARNING: Cannot read {filename}: {e}")
    return records


def report(name, status, detail):
    print(f"[{status}] {name}: {detail}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dir", default="/tmp",
        help="Directory containing PEEK runtime evidence",
    )
    args = parser.parse_args()
    root = Path(args.dir)

    print("===== B3 PEEK Runtime Evidence =====")
    print("Directory:", root)
    print()

    # 1. PEEK scheduling activity
    profiles = load_json_files(str(root / "peek_profile_*.json"))
    priority_calls = sum(
        int(data.get("calc_priority_calls", 0))
        for _, data in profiles
        if isinstance(data, dict)
    )

    report(
        "PEEK scheduling",
        "PASS" if priority_calls > 0 else "NOT VERIFIED",
        f"calc_priority_calls={priority_calls}",
    )

    # 2. Pending-tree synchronization
    validations = load_json_files(str(root / "peek_validate_*.json"))
    checks = sum(
        int(data.get("sync_checks", 0))
        for _, data in validations
        if isinstance(data, dict)
    )

    errors = {
        key: sum(
            int(data.get(key, 0))
            for _, data in validations
            if isinstance(data, dict)
        )
        for key in (
            "sync_extra_in_peek",
            "sync_missing_in_peek",
            "sync_token_mismatch",
        )
    }

    if checks == 0:
        status = "NOT VERIFIED"
    elif any(errors.values()):
        status = "FAIL"
    else:
        status = "PASS"

    report(
        "Pending-tree synchronization",
        status,
        f"sync_checks={checks}, errors={errors}",
    )

    # 3. Request arrival and scheduling timestamps
    phases = load_json_files(str(root / "peek_phases_*.json"))
    arrivals = 0
    picks = 0

    for _, data in phases:
        if not isinstance(data, dict):
            continue
        for timing in data.values():
            if not isinstance(timing, dict):
                continue
            if timing.get("arrive_ts") is not None:
                arrivals += 1
            if timing.get("pick_ts") is not None:
                picks += 1

    report(
        "Request phase tracking",
        "PASS" if picks > 0 else "NOT VERIFIED",
        f"arrivals={arrivals}, picks={picks}",
    )

    # 4. Actual eviction trace records
    trace_files = sorted(
        glob.glob(str(root / "peek_eviction_trace_*.jsonl"))
    )

    events = 0
    for filename in trace_files:
        try:
            with open(filename) as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(record, dict) and "ev_idx" in record:
                        events += 1
        except OSError as e:
            print(f"WARNING: Cannot read {filename}: {e}")

    report(
        "Eviction trace",
        "PASS" if events > 0 else "NOT VERIFIED",
        f"victim_records={events}",
    )

    print()
    print("Files found:")
    print(f"  Profile: {len(profiles)}")
    print(f"  Validation: {len(validations)}")
    print(f"  Phase: {len(phases)}")
    print(f"  Eviction trace: {len(trace_files)}")

    print()
    print("NOTE: Scheduling calls do not prove cLPM changed request order.")
    print("NOTE: Missing eviction records do not prove eviction is broken.")
    print("NOTE: Use fresh evidence from the intended server run.")


if __name__ == "__main__":
    main()

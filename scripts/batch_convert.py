#!/usr/bin/env python3
"""Batch convert all EUDAMED MIR DTX XML files in a folder to MIR 7.3.1 drafts."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add the scripts directory to the path so we can import the converter
sys.path.insert(0, str(Path(__file__).parent))
from xml_router import FORMAT_UNKNOWN, process_xml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-convert EUDAMED MIR XML files to MIR 7.3.1 drafts."
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        nargs="?",
        default=Path("20251128_Vigilance - XML samples"),
        help="Folder containing EUDAMED XML files (default: '20251128_Vigilance - XML samples')",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        nargs="?",
        default=Path("output"),
        help="Folder to write converted MIR 7.3.1 XML files (default: output/)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir: Path = args.input_dir
    output_dir: Path = args.output_dir

    xml_files = sorted(input_dir.glob("*.xml"))
    if not xml_files:
        print(f"No XML files found in {input_dir}", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    ok = skipped = errors = 0
    for xml_path in xml_files:
        raw = xml_path.read_bytes()

        out_path = output_dir / f"mir731_{xml_path.stem}.xml"
        try:
            processed = process_xml(raw, best_effort=True, full_template=False)
            detected = processed["detected_format"]
            if detected == FORMAT_UNKNOWN:
                print(f"[SKIP]  {xml_path.name}  (unsupported format)")
                skipped += 1
                continue

            out_path.write_bytes(processed["xml_bytes"])
            warnings = processed["warnings"]
            warning_hint = f" warnings={len(warnings)}" if warnings else ""
            print(f"[OK]    {xml_path.name}  →  {out_path.name}  ({detected}{warning_hint})")
            ok += 1
        except Exception as exc:
            print(f"[ERROR] {xml_path.name}: {exc}")
            errors += 1

    print(f"\nDone: {ok} converted, {skipped} skipped, {errors} errors.")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

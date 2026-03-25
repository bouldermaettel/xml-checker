#!/usr/bin/env python3
"""Batch convert all EUDAMED MIR DTX XML files in a folder to MIR 7.3.1 drafts."""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

from lxml import etree

# Add the scripts directory to the path so we can import the converter
sys.path.insert(0, str(Path(__file__).parent))
from eudamed_to_mir731 import build_tree, NS


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
        cleaned = re.sub(rb"<!--.*?-->", b"", raw, flags=re.DOTALL)
        try:
            source_tree = etree.parse(io.BytesIO(cleaned))
        except etree.XMLSyntaxError as exc:
            print(f"[PARSE ERROR] {xml_path.name}: {exc}")
            errors += 1
            continue

        # Check if this file is a supported MIR payload
        root = source_tree.getroot()
        service_id = None
        payload_type = None
        try:
            svc_nodes = root.xpath(
                "./message:recipient/message:service/service:serviceID", namespaces=NS
            )
            service_id = svc_nodes[0].text.strip() if svc_nodes else None
            pt_nodes = root.xpath(
                "./message:payload/vigbase:Dossier/vigbase:Data/@xsi:type", namespaces=NS
            )
            payload_type = pt_nodes[0].strip() if pt_nodes else None
        except Exception:
            pass

        if service_id != "VIG_DOSSIER" or payload_type != "vig:mir_2Type":
            print(f"[SKIP]  {xml_path.name}  (service={service_id}, type={payload_type})")
            skipped += 1
            continue

        out_path = output_dir / f"mir731_{xml_path.stem}.xml"
        try:
            target_tree = build_tree(source_tree)
            out_path.write_bytes(
                etree.tostring(target_tree, pretty_print=True, xml_declaration=True, encoding="UTF-8")
            )
            print(f"[OK]    {xml_path.name}  →  {out_path.name}")
            ok += 1
        except Exception as exc:
            print(f"[ERROR] {xml_path.name}: {exc}")
            errors += 1

    print(f"\nDone: {ok} converted, {skipped} skipped, {errors} errors.")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from lxml import etree

from scripts.eudamed_to_mir731 import NS
from scripts.xml_router import extract_all_xml_params, process_xml
from converter.backend.db import (
    find_by_hash,
    get_conversion,
    init_db,
    list_recent,
    save_conversion,
    reset_conversions,
)

app = FastAPI(title="EUDAMED to MIR 7.3.1 Converter API")
SUMMARY_HTML_PATH = Path(__file__).resolve().parents[2] / "reports" / "eudamed_mir731_summary.html"
FULL_MAPPING_HTML_PATH = Path(__file__).resolve().parents[2] / "scripts" / "field_mapping_template.html"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

init_db()

META_KEYS = [
    "reportType",
    "eventClassification",
    "mfrRef",
    "ncaReportNo",
    "brandName",
    "serviceId",
    "payloadType",
    "mfrAwarenessDate",
    "mfrAwarenessReportDate",
    "adverseEventDateFrom",
    "adverseEventDateTo",
    "reportNextDate",
    # Fields from eudamed_mir731_summary.html mapping matrix
    "mfrSRN",
    "udiDI",
    "udiPI",
    "nomenclatureCode",
    "deviceNomenclature",
    "serialNum",
    "batchNum",
    "deviceSoftwareVer",
    "deviceFirmwareVer",
    "eventDescription",
    "massKG",
    "heightCM",
    "patientPriorMedication",
    "healthcareFacilityName",
    "furtherInvestigations",
    "manufacturersFinalComments",
]


def _strip_comments(raw: bytes) -> bytes:
    return re.sub(rb"<!--.*?-->", b"", raw, flags=re.DOTALL)


def _select(root: etree._Element, xpath: str) -> str:
    nodes = root.xpath(xpath, namespaces=NS)
    if not nodes:
        return ""
    node = nodes[0]
    return (node.text or "").strip() if hasattr(node, "text") else str(node).strip()


def _normalize_meta(meta: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key in META_KEYS:
        value = str(meta.get(key, "")).strip()
        normalized[key] = value if value else "N/A"
    return normalized


def _looks_like_raw_eudamed_xml(xml_text: str) -> bool:
    snippet = xml_text[:600]
    return "<message:PullRequest" in snippet and "VIG_DOSSIER" in snippet


def _extract_html_tag_block(html: str, tag: str) -> str:
    pattern = rf"<{tag}[^>]*>(.*?)</{tag}>"
    match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_style_blocks(html: str) -> str:
    styles = re.findall(r"(<style[^>]*>.*?</style>)", html, flags=re.IGNORECASE | re.DOTALL)
    return "\n".join(styles)


def _extract_first_table(html: str) -> str:
    match = re.search(r"(<table[^>]*>.*?</table>)", html, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _build_combined_summary_html(full_mapping_html: str) -> str:
    template_styles = _extract_style_blocks(full_mapping_html)
    mapping_table = _extract_first_table(full_mapping_html)

    if not mapping_table:
        mapping_table = full_mapping_html

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>EUDAMED to MIR 7.3.1 Mapping Table</title>
  {template_styles}
  <style>
    body {{
      font-family: Georgia, serif;
      margin: 32px auto;
      max-width: 1200px;
      padding: 0 20px;
      line-height: 1.55;
      color: #1f2937;
      background: #faf7f0;
    }}
    h1 {{
      color: #0f766e;
      margin: 0 0 14px 0;
    }}
    section {{
      background: #fffdf8;
      border: 1px solid #e7dcc8;
      border-radius: 14px;
      padding: 20px;
    }}
    .mapping-wrap {{
      overflow-x: auto;
    }}
    .mapping-wrap table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
      background: #fff;
      table-layout: fixed;
    }}
    .mapping-wrap th,
    .mapping-wrap td {{
      text-align: left;
      border-bottom: 1px solid #e7dcc8;
      padding: 10px 8px;
      vertical-align: top;
      font-size: 0.9rem;
      word-break: break-word;
    }}
    .mapping-wrap th {{
      color: #6b7280;
      font-size: 0.82rem;
      text-transform: uppercase;
    }}
  </style>
</head>
<body>
  <section>
    <h1>EUDAMED to MIR 7.3.1 Complete Mapping</h1>
    <div class="mapping-wrap">
      {mapping_table}
    </div>
  </section>
</body>
</html>
"""


@app.get("/api/summary", response_class=HTMLResponse)
async def summary() -> HTMLResponse:
    if not FULL_MAPPING_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="Full mapping template not found.")

    full_mapping_html = FULL_MAPPING_HTML_PATH.read_text(encoding="utf-8")
    combined_html = _build_combined_summary_html(full_mapping_html)
    return HTMLResponse(content=combined_html)


@app.post("/api/convert")
async def convert(file: UploadFile, persist: bool = False):
    if not file.filename or not file.filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="Please upload an XML file (.xml).")

    raw = await file.read()
    try:
        source_tree = etree.parse(io.BytesIO(_strip_comments(raw)))
    except etree.XMLSyntaxError as exc:
        raise HTTPException(status_code=422, detail=f"XML parse error: {exc}")

    try:
        processed = process_xml(raw, best_effort=True, full_template=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    root = source_tree.getroot()
    xml_bytes = processed["xml_bytes"]
    xml_str = xml_bytes.decode("utf-8")
    converted_root = etree.fromstring(xml_bytes)

    stem = Path(file.filename).stem
    meta = dict(processed["meta"])
    if not meta.get("brandName"):
        meta["brandName"] = _select(converted_root, "./device_info/brandName")
    if not meta.get("serviceId"):
        meta["serviceId"] = _select(root, ".//service:serviceID")
    if not meta.get("payloadType"):
        meta["payloadType"] = _select(root, ".//service:payload/*/@xsi:type")
    meta = _normalize_meta(meta)

    response_payload = {
        "filename": f"mir731_{stem}.xml",
        "xml": xml_str,
        "detectedFormat": processed["detected_format"],
        "warnings": processed["warnings"],
        "inputSha1": processed["input_sha1"],
        "meta": meta,
    }

    if persist:
        existing = find_by_hash(processed["input_sha1"])
        if existing is not None:
            # Legacy records may contain raw EUDAMED XML for the same input hash.
            # Don't reuse those for conversion responses.
            if not (
                processed["detected_format"] == "EUDAMED_VIG_DTX"
                and _looks_like_raw_eudamed_xml(str(existing.get("xml", "")))
            ):
                # Don't propagate stale functional warnings from older records when
                # we explicitly signal a hash-based reuse.
                existing["warnings"] = ["DUPLICATE_INPUT_REUSED"]
                return JSONResponse(existing)

            existing_warnings = list(existing.get("warnings", []))
            if "LEGACY_EUDAMED_XML_REFRESHED" not in existing_warnings:
                existing_warnings.append("LEGACY_EUDAMED_XML_REFRESHED")
            response_payload["warnings"] = sorted(set(response_payload["warnings"] + existing_warnings))

        # Persist the complete extracted XML parameter dump as well.
        # This is useful for MIR uploads where you want "all fields"
        # instead of only the small curated `meta` subset.
        params_json = extract_all_xml_params(raw)

        conversion_id = save_conversion(
            input_filename=file.filename,
            input_format=processed["detected_format"],
            input_sha1=processed["input_sha1"],
            output_filename=response_payload["filename"],
            output_xml=response_payload["xml"],
            warnings=response_payload["warnings"],
            meta=meta,
            params_json=params_json,
            status="success",
        )
        response_payload["conversionId"] = conversion_id

    return JSONResponse(response_payload)


@app.get("/api/conversions")
async def conversions(limit: int = 20):
    safe_limit = max(1, min(limit, 200))
    return JSONResponse({"items": list_recent(safe_limit)})


@app.get("/api/conversions/{conversion_id}")
async def conversion_detail(conversion_id: int):
    item = get_conversion(conversion_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Conversion record not found.")
    return JSONResponse(item)

@app.post("/api/conversions/reset")
async def reset_db():
    cleared = reset_conversions()
    return JSONResponse({"ok": True, "clearedCount": cleared})


@app.post("/api/upload-db")
@app.post("/api/upload-mock")
async def upload_mock(file: UploadFile):
    if not file.filename or not file.filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="Please upload an XML file (.xml).")

    raw = await file.read()
    source_root: etree._Element | None = None
    try:
        source_tree = etree.parse(io.BytesIO(_strip_comments(raw)))
        source_root = source_tree.getroot()
    except etree.XMLSyntaxError:
        source_root = None

    try:
        processed = process_xml(raw, best_effort=True, full_template=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        params_json = extract_all_xml_params(raw)
    except etree.XMLSyntaxError as exc:
        raise HTTPException(status_code=422, detail=f"XML parse error: {exc}")

    existing = find_by_hash(processed["input_sha1"])
    if existing is not None:
        # Same legacy refresh behavior for upload-db path.
        if not (
            processed["detected_format"] == "EUDAMED_VIG_DTX"
            and _looks_like_raw_eudamed_xml(str(existing.get("xml", "")))
        ):
            return JSONResponse(
                {
                    "conversionId": existing.get("id"),
                    "inputFilename": existing.get("inputFilename", file.filename),
                    "detectedFormat": existing.get("detectedFormat", processed["detected_format"]),
                    "inputSha1": existing.get("inputSha1", processed["input_sha1"]),
                    "status": existing.get("status", "uploaded"),
                    # Keep duplicate response explicit and avoid stale warning carry-over.
                    "warnings": ["DUPLICATE_INPUT_REUSED"],
                }
            )

    stem = Path(file.filename).stem
    # Store the converted MIR output XML (or the same XML if MIR input).
    # We still extract params_json from the original uploaded raw bytes.
    real_xml = processed["xml_bytes"].decode("utf-8", errors="replace")
    real_meta = dict(processed.get("meta", {}))
    if source_root is not None:
        if not real_meta.get("serviceId"):
            real_meta["serviceId"] = _select(source_root, ".//service:serviceID")
        if not real_meta.get("payloadType"):
            real_meta["payloadType"] = _select(source_root, ".//service:payload/*/@xsi:type")
    real_meta = _normalize_meta(real_meta)
    warnings = list(processed["warnings"])

    conversion_id = save_conversion(
        input_filename=file.filename,
        input_format=processed["detected_format"],
        input_sha1=processed["input_sha1"],
        output_filename=f"uploaded_{stem}.xml",
        output_xml=real_xml,
        warnings=warnings,
        meta=real_meta,
        params_json=params_json,
        status="uploaded",
    )

    return JSONResponse(
        {
            "conversionId": conversion_id,
            "inputFilename": file.filename,
            "detectedFormat": processed["detected_format"],
            "inputSha1": processed["input_sha1"],
            "status": "uploaded",
            "warnings": warnings,
        }
    )

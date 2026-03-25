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

from scripts.eudamed_to_mir731 import NS, build_tree, ensure_supported

app = FastAPI(title="EUDAMED to MIR 7.3.1 Converter API")
SUMMARY_HTML_PATH = Path(__file__).resolve().parents[2] / "reports" / "eudamed_mir731_summary.html"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _strip_comments(raw: bytes) -> bytes:
    return re.sub(rb"<!--.*?-->", b"", raw, flags=re.DOTALL)


def _select(root: etree._Element, xpath: str) -> str:
    nodes = root.xpath(xpath, namespaces=NS)
    if not nodes:
        return ""
    node = nodes[0]
    return (node.text or "").strip() if hasattr(node, "text") else str(node).strip()


@app.get("/api/summary", response_class=HTMLResponse)
async def summary() -> HTMLResponse:
    if not SUMMARY_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="Summary report not found.")
    return HTMLResponse(content=SUMMARY_HTML_PATH.read_text(encoding="utf-8"))


@app.post("/api/convert")
async def convert(file: UploadFile):
    if not file.filename or not file.filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="Please upload an XML file (.xml).")

    raw = await file.read()
    cleaned = _strip_comments(raw)

    try:
        source_tree = etree.parse(io.BytesIO(cleaned))
    except etree.XMLSyntaxError as exc:
        raise HTTPException(status_code=422, detail=f"XML parse error: {exc}")

    root = source_tree.getroot()

    try:
        ensure_supported(root)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    result_tree = build_tree(source_tree)
    converted_root = result_tree.getroot()
    xml_bytes = etree.tostring(
        converted_root,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
    )
    xml_str = xml_bytes.decode("utf-8")

    stem = Path(file.filename).stem
    meta = {
        "reportType": _select(root, ".//vig:reportType"),
        "eventClassification": _select(root, ".//vig:eventClassification"),
        "mfrRef": _select(root, ".//vig:mfrRef"),
        "ncaReportNo": _select(root, ".//vig:ncaReportNo"),
        # Extract from converted MIR output because EUDAMED source does not expose vig:brandName directly.
        "brandName": _select(converted_root, "./device_info/brandName"),
        "serviceId": _select(root, ".//service:serviceID"),
        "payloadType": _select(root, ".//service:payload/*/@xsi:type"),
    }

    return JSONResponse({
        "filename": f"mir731_{stem}.xml",
        "xml": xml_str,
        "meta": meta,
    })

from __future__ import annotations

import hashlib
import io
import re
from typing import Any

from lxml import etree

try:
    from scripts.eudamed_to_mir731 import (
        NS,
        build_tree,
        EVENT_CLASSIFICATION_MAP,
        REPORT_TYPE_MAP,
    )
except ModuleNotFoundError:
    from eudamed_to_mir731 import (
        NS,
        build_tree,
        EVENT_CLASSIFICATION_MAP,
        REPORT_TYPE_MAP,
    )

FORMAT_MIR_731_NATIVE = "MIR_731_NATIVE"
FORMAT_EUDAMED_VIG_DTX = "EUDAMED_VIG_DTX"
FORMAT_UNKNOWN = "UNKNOWN"


def strip_xml_comments(raw: bytes) -> bytes:
    return re.sub(rb"<!--.*?-->", b"", raw, flags=re.DOTALL)


def parse_xml(raw: bytes) -> etree._ElementTree:
    cleaned = strip_xml_comments(raw)
    return etree.parse(io.BytesIO(cleaned))


def _select(root: etree._Element, xpath: str) -> str:
    nodes = root.xpath(xpath, namespaces=NS)
    if not nodes:
        return ""
    node = nodes[0]
    return (node.text or "").strip() if hasattr(node, "text") else str(node).strip()


def _select_date(root: etree._Element, xpath: str) -> str:
    """Extract a date-like string and normalize it to YYYY-MM-DD when possible."""
    value = _select(root, xpath)
    if not value:
        return ""
    # Handles both pure dates (YYYY-MM-DD) and timestamps (YYYY-MM-DDTHH:MM:SS....)
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return value[:10]
    return value


def extract_all_xml_params(raw: bytes) -> dict[str, str]:
    """
    Extract *all* XML parameters from the uploaded XML:
    - element text values (including empty/blank -> "")
    - attribute values (including empty -> "")

    The output is a deterministic mapping of "path -> value", where the path is namespace-safe
    (using local-name) and disambiguated by sibling index.
    """
    tree = parse_xml(raw)
    root = tree.getroot()

    def local_name(tag: str | etree.QName) -> str:
        return etree.QName(tag).localname

    def attr_local(attr_key: str) -> str:
        # lxml uses "{namespace}local" for namespaced attributes in .attrib keys.
        if attr_key.startswith("{") and "}" in attr_key:
            return attr_key.split("}", 1)[1]
        return attr_key

    params: dict[str, str] = {}

    def walk(elem: etree._Element, path_parts: list[str]) -> None:
        path = "/" + "/".join(path_parts)

        # Element text (including explicit empty when missing/whitespace-only).
        raw_text = elem.text
        text_value = "" if raw_text is None else raw_text.strip()
        params[f"{path}/text"] = text_value

        # Attributes on this element.
        for akey, aval in elem.attrib.items():
            params[f"{path}/@{attr_local(akey)}"] = "" if aval is None else str(aval)

        # Children: disambiguate by local-name + sibling index.
        if len(elem):
            sibling_counts: dict[str, int] = {}
            for child in elem:
                cname = local_name(child.tag)
                sibling_counts[cname] = sibling_counts.get(cname, 0) + 1
                cidx = sibling_counts[cname]
                walk(child, path_parts + [f"{cname}[{cidx}]"])

    root_name = local_name(root.tag)
    walk(root, [f"{root_name}[1]"])
    return params


def detect_format(root: etree._Element) -> str:
    local_name = etree.QName(root).localname
    if local_name == "incident":
        version = root.get("version", "")
        if version.startswith("7.3"):
            return FORMAT_MIR_731_NATIVE

    service_id = _select(root, "./message:recipient/message:service/service:serviceID")
    payload_type = _select(root, "./message:payload/vigbase:Dossier/vigbase:Data/@xsi:type")
    supported_payloads = {"vig:mir_2Type", "vig:fsnType", "vig:fsca_2Type"}
    if service_id == "VIG_DOSSIER" and payload_type in supported_payloads:
        return FORMAT_EUDAMED_VIG_DTX

    return FORMAT_UNKNOWN


def _meta_from_mir(converted_root: etree._Element) -> dict[str, str]:
    return {
        "reportType": (converted_root.findtext("./admin_info/reportType") or "").strip(),
        "eventClassification": (converted_root.findtext("./admin_info/eventClassification") or "").strip(),
        "mfrRef": (converted_root.findtext("./admin_info/mfrRef") or "").strip(),
        "ncaReportNo": (converted_root.findtext("./admin_info/ncaReportNo") or "").strip(),
        "brandName": (converted_root.findtext("./device_info/brandName") or "").strip(),
        "serviceId": "",
        "payloadType": "",
        "mfrAwarenessDate": (converted_root.findtext("./admin_info/mfrAwarenessDate") or "").strip(),
        "mfrAwarenessReportDate": (converted_root.findtext("./admin_info/mfrAwarenessReportDate") or "").strip(),
        "adverseEventDateFrom": (converted_root.findtext("./admin_info/adverseEventDateFrom") or "").strip(),
        "adverseEventDateTo": (converted_root.findtext("./admin_info/adverseEventDateTo") or "").strip(),
        "reportNextDate": (converted_root.findtext("./admin_info/reportNextDate") or "").strip(),
        # Additional fields from the mapping matrix (EUDAMED -> MIR 7.3.1)
        "mfrSRN": (converted_root.findtext("./contact_info/reporterMfr/mfrDetails/mfrSRN") or "").strip(),
        "udiDI": (converted_root.findtext("./device_info/udiDI") or "").strip(),
        "udiPI": (converted_root.findtext("./device_info/udiPI") or "").strip(),
        "nomenclatureCode": (converted_root.findtext("./device_info/nomenclatureCode") or "").strip(),
        "deviceNomenclature": (converted_root.findtext("./device_info/deviceNomenclature") or "").strip(),
        "serialNum": (converted_root.findtext("./device_info/serialNum") or "").strip(),
        "batchNum": (converted_root.findtext("./device_info/batchNum") or "").strip(),
        "deviceSoftwareVer": (converted_root.findtext("./device_info/deviceSoftwareVer") or "").strip(),
        "deviceFirmwareVer": (converted_root.findtext("./device_info/deviceFirmwareVer") or "").strip(),
        "eventDescription": (converted_root.findtext("./incident_info/clinical_event_info/eventDescription") or "").strip(),
        "massKG": (converted_root.findtext("./incident_info/patient_info/massKG") or "").strip(),
        "heightCM": (converted_root.findtext("./incident_info/patient_info/heightCM") or "").strip(),
        "patientPriorMedication": (converted_root.findtext("./incident_info/patient_info/patientPriorMedication") or "").strip(),
        "healthcareFacilityName": (converted_root.findtext("./incident_info/initial_reporter_info/healthcareFacilityName") or "").strip(),
        "furtherInvestigations": (converted_root.findtext("./mfr_invest/furtherInvestigations") or "").strip(),
        "manufacturersFinalComments": (converted_root.findtext("./mfr_invest/manufacturersFinalComments") or "").strip(),
    }


def _meta_from_source_and_mir(source_root: etree._Element, converted_root: etree._Element) -> dict[str, str]:
    report_type_raw = _select(source_root, ".//vig:reportType") or "INITIAL"
    event_class_raw = _select(source_root, ".//vig:eventClassification") or "DEATH"

    # Extract from EUDAMED source using the mapping matrix sources.
    # For brand/trade name we reuse the already-built MIR mapping (same fallback rules).
    device_nomenclature = _select(source_root, ".//vig:deviceNomenclatureDescription_manual")
    if not device_nomenclature:
        device_nomenclature = _select(source_root, ".//vig:deviceNomenclatureDescription")

    return {
        # Normalize enums to MIR output representation (matches build_tree behavior).
        "reportType": REPORT_TYPE_MAP.get(report_type_raw, "Initial"),
        "eventClassification": EVENT_CLASSIFICATION_MAP.get(event_class_raw, "Death"),
        "mfrRef": _select(source_root, ".//vig:mfr"),
        "ncaReportNo": _select(source_root, ".//vig:ncaReportRef"),
        "brandName": (converted_root.findtext("./device_info/brandName") or "").strip(),
        "serviceId": _select(source_root, ".//service:serviceID"),
        "payloadType": _select(source_root, ".//service:payload/*/@xsi:type"),
        "mfrAwarenessDate": _select_date(source_root, ".//vig:mfAwarenessDate"),
        "mfrAwarenessReportDate": _select_date(source_root, ".//vig:mfAwarenessDateReportability"),
        "adverseEventDateFrom": _select_date(source_root, ".//vig:startDateofIncident"),
        "adverseEventDateTo": _select_date(source_root, ".//vig:endDateofIncident"),
        "reportNextDate": _select_date(source_root, ".//vig:reportNextDate"),

        # Additional fields from the mapping matrix (EUDAMED -> MIR 7.3.1)
        "mfrSRN": _select(source_root, ".//vig:mf_srn"),
        "udiDI": _select(source_root, ".//vig:deviceUUID/vigbase:udiDiCode"),
        "udiPI": _select(source_root, ".//vig:udiPIvalue"),
        "nomenclatureCode": _select(source_root, ".//vig:deviceNomenclatureCode"),
        "deviceNomenclature": device_nomenclature,
        "serialNum": _select(source_root, ".//vig:affectedSerialNo"),
        "batchNum": _select(source_root, ".//vig:affectedLotNo"),
        "deviceSoftwareVer": _select(source_root, ".//vig:affectedSoftwareNo"),
        "deviceFirmwareVer": _select(source_root, ".//vig:affectedFirmwareNo"),
        "eventDescription": _select(source_root, ".//vig:natureOfIncident"),
        "massKG": _select(source_root, ".//vig:patientWeight"),
        "heightCM": _select(source_root, ".//vig:patientHeight"),
        "patientPriorMedication": _select(source_root, ".//vig:patientHealthConditions"),
        "healthcareFacilityName": _select(source_root, ".//vig:healthcareFacilityName"),
        "furtherInvestigations": _select(source_root, ".//vig:furtherInvestigations"),
        "manufacturersFinalComments": _select(source_root, ".//vig:causeInvestigationConclusions"),
    }


def process_xml(raw: bytes, *, best_effort: bool = True, full_template: bool = False) -> dict[str, Any]:
    warnings: list[str] = []
    source_tree = parse_xml(raw)
    source_root = source_tree.getroot()
    detected = detect_format(source_root)

    if detected == FORMAT_UNKNOWN:
        raise ValueError(
            "Unsupported XML format. Expected MIR 7.3.x incident or EUDAMED VIG_DOSSIER payloads (mir_2Type / fsnType / fsca_2Type)."
        )

    if detected == FORMAT_MIR_731_NATIVE:
        converted_root = source_root
        xml_bytes = etree.tostring(
            source_tree,
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8",
        )
        meta = _meta_from_mir(converted_root)
    else:
        try:
            result_tree = build_tree(source_tree, full_template=full_template, validate=not best_effort)
        except ValueError as exc:
            if not best_effort:
                raise
            warnings.append(f"VALIDATION_SKIPPED: {exc}")
            result_tree = build_tree(source_tree, full_template=full_template, validate=False)

        converted_root = result_tree.getroot()
        xml_bytes = etree.tostring(
            result_tree,
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8",
        )
        meta = _meta_from_source_and_mir(source_root, converted_root)

    for marker in ("REVIEW_REQUIRED", "review_required@example.com"):
        if marker in xml_bytes.decode("utf-8"):
            warnings.append("MISSING_REQUIRED_TARGET_FIELD")
            break

    return {
        "detected_format": detected,
        "xml_bytes": xml_bytes,
        "meta": meta,
        "warnings": warnings,
        "input_sha1": hashlib.sha1(raw).hexdigest(),
    }

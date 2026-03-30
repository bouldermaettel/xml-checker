from __future__ import annotations

import argparse
import io
import re
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lxml import etree

try:
    from scripts.xsd_to_xml_template import build_template_tree_from_xsd
except ModuleNotFoundError:
    from xsd_to_xml_template import build_template_tree_from_xsd

from scripts.mapping_loader import load_mapping_table

NS = {
    "message": "https://ec.europa.eu/tools/eudamed/dtx/servicemodel/Message/v1",
    "service": "https://ec.europa.eu/tools/eudamed/dtx/servicemodel/Service/v1",
    "vig": "https://ec.europa.eu/tools/eudamed/dtx/datamodel/Entity/Vigilance/v1",
    "vigbase": "https://ec.europa.eu/tools/eudamed/dtx/datamodel/Entity/Vigilance",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

REPORT_TYPE_MAP = {
    "INITIAL": "Initial",
    "FOLLOW_UP": "Follow up",
    # For the MIR 7.3.1 XSDs, the FINAL variant is further split into
    # "Final (Reportable incident)" vs "Final (Non-reportable incident)".
    # EUDAMED payload samples we process do not expose the distinction,
    # so we default to the reportable variant as best-effort.
    "FINAL": "Final (Reportable incident)",
    # Field Safety Corrective Action (FSCA) variants seen in some EUDAMED exports.
    # We normalize them to the corresponding MIR incident report types.
    "FSCA_INITIAL": "Initial",
    "FSCA_FOLLOW_UP": "Follow up",
    "FSCA_FINAL": "Final (Reportable incident)",
}

EVENT_CLASSIFICATION_MAP = {
    "DEATH": "Death",
    "SERIOUS_PUBLIC_HEALTH_THREAT": "Serious public health threat",
    "UNANTICIPATED_SERIOUS_DETERIORATION": "Unanticipated serious deterioration in state of health",
}

GENDER_MAP = {
    "MALE": "Male",
    "FEMALE": "Female",
    "UNKNOWN": "Unknown",
    "OTHER": "Other",
}

INITIAL_REPORTER_ROLE_MAP = {
    "HEALTHCARE_PROFESSIONAL": "Healthcare professional",
    "PATIENT": "Patient",
    "LAY_USER": "Lay user",
    "OTHER": "Other",
}

MAPPING_CSV_PATH = Path(__file__).parent / "field_mapping_template.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert EUDAMED MIR to MIR 7.3.1 draft XML")
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument(
        "--full-template",
        action="store_true",
        help="Emit full XSD-shaped XML with mapped values overlaid (includes optional fields).",
    )
    return parser.parse_args()


def select_text(node: etree._Element, xpath: str) -> Optional[str]:
    result = node.xpath(xpath, namespaces=NS)
    if not result:
        return None
    value = result[0]
    if isinstance(value, etree._Element):
        return (value.text or "").strip() or None
    return str(value).strip() or None


def iso_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.replace("Z", "+0000")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(normalized, fmt).date().isoformat()
        except ValueError:
            continue
    return value[:10]


def append_text(parent: etree._Element, tag: str, value: Optional[str]) -> None:
    if value in (None, ""):
        return
    child = etree.SubElement(parent, tag)
    child.text = value


@lru_cache(maxsize=1)
def initial_schema() -> etree.XMLSchema:
    # Kept for backward-compat; prefer ensure_xsd_compliant() which selects by reportType.
    xsd_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "20250505_MIR_7.3.1"
        / "incident-Initial-v7.3.xsd"
    )
    return etree.XMLSchema(etree.parse(str(xsd_path)))

def _xsd_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "20250505_MIR_7.3.1"


@lru_cache(maxsize=8)
def load_schema(xsd_filename: str) -> etree.XMLSchema:
    xsd_path = _xsd_dir() / xsd_filename
    return etree.XMLSchema(etree.parse(str(xsd_path)))


def candidate_schemas_for_report_type(report_type_raw: str) -> list[str]:
    report_type_raw = (report_type_raw or "").strip()
    if report_type_raw in ("INITIAL", "FSCA_INITIAL"):
        return ["incident-Initial-v7.3.xsd", "incident-InitialFinal-v7.3.xsd"]
    if report_type_raw in ("FOLLOW_UP", "FSCA_FOLLOW_UP"):
        return ["incident-Followup-v7.3.xsd", "incident-InitialFinal-v7.3.xsd"]
    if report_type_raw in ("FINAL", "FSCA_FINAL"):
        return [
            "incident-FinalRep-v7.3.xsd",
            "incident-FinalNonRep-v7.3.xsd",
            "incident-InitialFinal-v7.3.xsd",
        ]
    # Fallback: best effort with the most permissive template/schema.
    return ["incident-Initial-v7.3.xsd", "incident-InitialFinal-v7.3.xsd"]


def ensure_xsd_compliant(tree: etree._ElementTree, report_type_raw: str) -> None:
    # We try multiple XSDs because FINAL variants may depend on further subtypes
    # (rep vs non-rep), and we want the converter to be less brittle.
    last_details = ""
    for xsd_filename in candidate_schemas_for_report_type(report_type_raw):
        schema = load_schema(xsd_filename)
        if schema.validate(tree):
            return
        details = "; ".join(err.message for err in schema.error_log)
        last_details = f"{xsd_filename}: {details}"

    raise ValueError(
        f"Generated output is not compliant with any candidate XSD for reportType={report_type_raw!r}: {last_details}"
    )


def ensure_supported(root: etree._Element) -> None:
    service_id = select_text(root, "./message:recipient/message:service/service:serviceID")
    payload_type = select_text(root, "./message:payload/vigbase:Dossier/vigbase:Data/@xsi:type")
    supported_payloads = {"vig:mir_2Type", "vig:fsnType", "vig:fsca_2Type"}
    if service_id != "VIG_DOSSIER" or payload_type not in supported_payloads:
        raise ValueError(f"Unsupported payload: service_id={service_id!r}, payload_type={payload_type!r}")


def merge_values(template_elem: etree._Element, source_elem: etree._Element) -> None:
    for attr_name, attr_value in source_elem.attrib.items():
        template_elem.set(attr_name, attr_value)

    source_text = (source_elem.text or "").strip()
    if source_text:
        template_elem.text = source_text

    source_by_tag: dict[str, list[etree._Element]] = {}
    for child in source_elem:
        source_by_tag.setdefault(child.tag, []).append(child)

    used_by_tag: dict[str, int] = {}
    for tchild in template_elem:
        candidates = source_by_tag.get(tchild.tag)
        if not candidates:
            continue
        idx = used_by_tag.get(tchild.tag, 0)
        if idx >= len(candidates):
            continue
        used_by_tag[tchild.tag] = idx + 1
        merge_values(tchild, candidates[idx])


def _template_xsd_for_report_type(report_type_raw: str) -> Path:
    xsd_dir = _xsd_dir()
    report_type_raw = (report_type_raw or "").strip()
    if report_type_raw in ("INITIAL", "FSCA_INITIAL"):
        return xsd_dir / "incident-Initial-v7.3.xsd"
    if report_type_raw in ("FOLLOW_UP", "FSCA_FOLLOW_UP"):
        return xsd_dir / "incident-Followup-v7.3.xsd"
    if report_type_raw in ("FINAL", "FSCA_FINAL"):
        # InitialFinal is the most generic choice among the provided schemas.
        return xsd_dir / "incident-InitialFinal-v7.3.xsd"
    return xsd_dir / "incident-Initial-v7.3.xsd"


def to_full_template(mapped_tree: etree._ElementTree, report_type_raw: str) -> etree._ElementTree:
    template_tree = build_template_tree_from_xsd(_template_xsd_for_report_type(report_type_raw))
    merge_values(template_tree.getroot(), mapped_tree.getroot())
    return template_tree


def get_value_by_xpath(root: etree._Element, xpath: str) -> Optional[str]:
    try:
        return select_text(root, xpath)
    except Exception:
        return None


def build_tree(
    source_tree: etree._ElementTree,
    *,
    full_template: bool = False,
    validate: bool = True,
) -> etree._ElementTree:
    root = source_tree.getroot()
    ensure_supported(root)

    mapping_table = load_mapping_table(MAPPING_CSV_PATH)
    # Build a dict for MIR field path → value
    mir_values = {}
    for row in mapping_table:
        eudamed_path = row["EUDAMED Field Path"]
        mir_path = row["MIR Field Path"]
        mapping_type = row["Mapping Type"]
        # Only process if both paths are present
        if not eudamed_path or not mir_path:
            continue
        value = get_value_by_xpath(root, eudamed_path)
        # TODO: Add transformation logic based on mapping_type if needed
        mir_values[mir_path] = value

    dossier = root.xpath("./message:payload/vigbase:Dossier", namespaces=NS)[0]

    data_container = dossier.xpath("./vigbase:Data", namespaces=NS)
    if not data_container:
        raise ValueError("EUDAMED DTX dossier has no vigbase:Data payload.")
    data_container = data_container[0]

    payload_kind: str | None = None
    payload_data: etree._Element | None = None
    for kind, xp in (("mir_2", "./vig:mir_2"), ("fsn", "./vig:fsn"), ("fsca_2", "./vig:fsca_2")):
        nodes = data_container.xpath(xp, namespaces=NS)
        if nodes:
            payload_kind = kind
            payload_data = nodes[0]
            break

    if payload_data is None or payload_kind is None:
        raise ValueError("Unsupported vigbase:Data subtype. Expected mir_2, fsn, or fsca_2.")

    now_date = datetime.now(timezone.utc).date().isoformat()

    def sel_text(elem: etree._Element, xps: list[str], default: str) -> str:
        for xp in xps:
            v = select_text(elem, xp)
            if v:
                return v
        return default

    def sel_date(elem: etree._Element, xps: list[str]) -> str | None:
        for xp in xps:
            v = select_text(elem, xp)
            norm = iso_date(v)
            if norm:
                return norm
        return None

    def select_all_texts(elem: etree._Element, xpath: str) -> list[str]:
        nodes = elem.xpath(xpath, namespaces=NS)
        values: list[str] = []
        for node in nodes:
            if hasattr(node, "text"):
                val = (node.text or "").strip()
            else:
                val = str(node).strip()
            if val:
                values.append(val)
        return values

    nca_ref_multi_values: list[str] = []
    mfr_ref_multi_values: list[str] = []
    nca_fsca_values: list[str] = []
    mfr_fsca_values: list[str] = []
    pmcf_pmpf_id_values: list[str] = []
    pmcf_question: str | None = None
    psr_id_values: list[str] = []

    # Compute report / classification and shared dates first.
    if payload_kind == "mir_2":
        report_type_raw = select_text(payload_data, "./vig:administrativeInformation/vig:adminInfoSection/vig:reportType") or "INITIAL"
        event_class_raw = select_text(
            payload_data, "./vig:administrativeInformation/vig:dateOfIncidentSection/vig:eventClassification"
        ) or "DEATH"

        adverse_from = iso_date(
            select_text(payload_data, "./vig:administrativeInformation/vig:dateOfIncidentSection/vig:startDateofIncident")
        ) or now_date
        adverse_to = iso_date(
            select_text(payload_data, "./vig:administrativeInformation/vig:dateOfIncidentSection/vig:endDateofIncident")
        ) or now_date
        mfr_awareness_date = iso_date(
            select_text(payload_data, "./vig:administrativeInformation/vig:dateOfIncidentSection/vig:mfAwarenessDate")
        ) or now_date
        mfr_awareness_report_date = iso_date(
            select_text(payload_data, "./vig:administrativeInformation/vig:dateOfIncidentSection/vig:mfAwarenessDateReportability")
        ) or now_date
        report_next_date = iso_date(
            select_text(payload_data, "./vig:administrativeInformation/vig:dateOfIncidentSection/vig:reportNextDate")
        ) or now_date

        brand_or_nomenclature = (
            select_text(
                payload_data,
                ".//vig:deviceInformationSubHead/vig:deviceNomenclatureDescription_manual",
            )
            or select_text(payload_data, ".//vig:deviceInformationSubHead/vig:deviceNomenclatureDescription")
            or "REVIEW_REQUIRED"
        )

        nca_report_no = (
            select_text(payload_data, "./vig:administrativeInformation/vig:adminInfoSection/vig:ncaReportRef")
            or select_text(dossier, "./vigbase:DossierExtId")
            or "REVIEW_REQUIRED"
        )

        # EUDAMED "otherReportsReferencesSection" contains listOfMIRForm entries
        # with `ncaRefNumber` and `mfrRefNumber` (ordinal=1..n). We currently
        # map the MIR "eudamed" number fields from these values.
        nca_ref_multi_values = select_all_texts(
            payload_data,
            "./vig:administrativeInformation/vig:otherReportsReferencesSection/vig:refNumbersOtherMIRSection/vig:listOfMIRForm/vig:ncaRefNumber",
        )
        mfr_ref_multi_values = select_all_texts(
            payload_data,
            "./vig:administrativeInformation/vig:otherReportsReferencesSection/vig:refNumbersOtherMIRSection/vig:listOfMIRForm/vig:mfrRefNumber",
        )

        # FSCA reference numbers (similar structure, different element names).
        nca_fsca_values = select_all_texts(
            payload_data,
            "./vig:administrativeInformation/vig:otherReportsReferencesSection/vig:refNumbersFSCASection/vig:listOfFSCANumbers/vig:ncaFSCANumber",
        )
        mfr_fsca_values = select_all_texts(
            payload_data,
            "./vig:administrativeInformation/vig:otherReportsReferencesSection/vig:refNumbersFSCASection/vig:listOfFSCANumbers/vig:mfrFSCANumber",
        )

        # PMCF/PMPF investigation info.
        pmcf_raw = select_text(payload_data, ".//vig:pmcf_pmpfInvestigationSection/vig:isPMCF") or ""
        if pmcf_raw.lower() == "true":
            pmcf_question = "Yes"
        elif pmcf_raw.lower() == "false":
            pmcf_question = "No"

        pmcf_pmpf_id_values = select_all_texts(
            payload_data,
            ".//vig:pmcf_pmpfInvestigationSection/vig:pmcf_pmpfInvestigationID",
        )

        # PSR related info is present in some payload variants.
        psr_related_raw = select_text(payload_data, ".//vig:is_psr_related") or ""
        if psr_related_raw.lower() == "true":
            psr_id_values = [select_text(dossier, "./vigbase:DossierExtId") or ""]
            psr_id_values = [v for v in psr_id_values if v]
    elif payload_kind == "fsn":
        report_type_raw = (
            select_text(
                payload_data,
                "./vig:fsnAdministrativeInformationSection/vig:fsnInformation/vig:reportType",
            )
            or "FINAL"
        )
        event_class_raw = "DEATH"

        report_date = sel_date(
            payload_data,
            ["./vig:fsnAdministrativeInformationSection/vig:fsnInformation/vig:reportDate", ".//vig:reportDate"],
        ) or now_date
        adverse_from = report_date
        adverse_to = report_date
        mfr_awareness_date = report_date
        mfr_awareness_report_date = report_date
        report_next_date = report_date

        brand_or_nomenclature = (
            select_text(payload_data, ".//vig:deviceNomenclatureDescriptionSelected")
            or select_text(payload_data, ".//vig:deviceNomenclatureCodeSelected")
            or "REVIEW_REQUIRED"
        )
        nca_report_no = select_text(dossier, "./vigbase:DossierExtId") or "REVIEW_REQUIRED"
    else:  # fsca_2
        report_type_raw = (
            select_text(
                payload_data,
                "./vig:generalInformation/vig:generalInformationSection/vig:reportType",
            )
            or "FSCA_INITIAL"
        )
        event_class_raw = "DEATH"

        decision_date = sel_date(
            payload_data,
            ["./vig:generalInformation/vig:generalInformationSection/vig:dateFSCADecision", ".//vig:dateFSCADecision"],
        ) or now_date
        adverse_from = decision_date
        adverse_to = decision_date
        mfr_awareness_date = decision_date
        mfr_awareness_report_date = decision_date
        report_next_date = decision_date

        brand_or_nomenclature = (
            select_text(payload_data, ".//vig:deviceNomenclatureDescriptionSelected")
            or select_text(payload_data, ".//vig:deviceNomenclatureCodeSelected")
            or "REVIEW_REQUIRED"
        )
        nca_report_no = select_text(dossier, "./vigbase:DossierExtId") or "REVIEW_REQUIRED"

    incident = etree.Element(
        "incident",
        version="7.3.1",
        sCreateTimeStamp=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        sFormLanguage="en",
    )

    admin_info = etree.SubElement(incident, "admin_info")
    append_text(admin_info, "formVersion", "7.3.1")
    append_text(admin_info, "ncaName", select_text(dossier, "./vigbase:Fields/vig:ca_srn") or "REVIEW_REQUIRED")

    primary_nca_ref = nca_ref_multi_values[0] if nca_ref_multi_values else None
    primary_mfr_ref = mfr_ref_multi_values[0] if mfr_ref_multi_values else None
    append_text(admin_info, "ncaEudamedNum", primary_nca_ref)
    append_text(admin_info, "ncaReportNo", nca_report_no)
    append_text(admin_info, "refNumEudamed", primary_mfr_ref)
    append_text(admin_info, "reportDate", now_date)
    append_text(admin_info, "adverseEventDateFrom", adverse_from)
    append_text(admin_info, "adverseEventDateTo", adverse_to)
    append_text(admin_info, "mfrAwarenessDate", mfr_awareness_date)
    append_text(admin_info, "mfrAwarenessReportDate", mfr_awareness_report_date)
    append_text(admin_info, "reportType", REPORT_TYPE_MAP.get(report_type_raw, "Initial"))
    append_text(admin_info, "reportNextDate", report_next_date)
    append_text(admin_info, "eventClassification", EVENT_CLASSIFICATION_MAP.get(event_class_raw, "Death"))

    # admin_infoT sequence order in MIR 7.3.1 XSD:
    # formVersion, ncaName, ncaEudamedNum, ncaReportNo, refNumEudamed,
    # reportDate, adverseEventDateFrom, adverseEventDateTo,
    # mfrAwarenessDate, mfrAwarenessReportDate, reportType, reportNextDate,
    # eventClassification, contact_info, mfrRef,
    # (then optional: ncaRefMultiDev, ncaRefMultiDevLI, eudamedRefMultiDev, eudamedRefMultiDevLI,
    #  mfrRefMultiDev, mfrRefMultiDevLI, ncaRefFSCA, ncaRefFSCALI, eudamedRefFSCA,
    #  eudamedRefFSCALI, mfrRefFSCA, mfrRefFSCALI, psrId, psrIdLI,
    #  pmcfpmpfQuestion, pmcfpmpfId, pmcfpmpfIdLI)
    # Keep this order when adding new populated fields.

    contact_info = etree.SubElement(admin_info, "contact_info")
    reporter_mfr = etree.SubElement(contact_info, "reporterMfr")
    append_text(reporter_mfr, "statusReporter", "Manufacturer")
    mfr_details = etree.SubElement(reporter_mfr, "mfrDetails")
    append_text(mfr_details, "mfrName", select_text(dossier, "./vigbase:Fields/vig:mf_srn") or "REVIEW_REQUIRED")
    append_text(mfr_details, "mfrSRN", select_text(dossier, "./vigbase:Fields/vig:mf_srn") or "REVIEW_REQUIRED")
    append_text(mfr_details, "mfrContactPersonFirstName", select_text(payload_data, ".//vig:mfrContact/vig:firstName") or "REVIEW_REQUIRED")
    append_text(mfr_details, "mfrContactPersonSecondName", select_text(payload_data, ".//vig:mfrContact/vig:familyName") or "REVIEW_REQUIRED")
    mfr_city = (
        select_text(payload_data, ".//vig:mfrContact/vig:geographicalAddress/vig:cityName")
        or select_text(payload_data, ".//vig:arInformationSection/vig:arContact/vig:geographicalAddress/vig:cityName")
        or "Unknown"
    )
    append_text(mfr_details, "mfrCity", mfr_city)
    append_text(mfr_details, "mfrCountry", "MT")
    mfr_postcode = (
        select_text(payload_data, ".//vig:mfrContact/vig:geographicalAddress/vig:postalZone")
        or select_text(payload_data, ".//vig:arInformationSection/vig:arContact/vig:geographicalAddress/vig:postalZone")
        or "00000"
    )
    append_text(mfr_details, "mfrPostcode", mfr_postcode)
    append_text(mfr_details, "mfrPhone", select_text(payload_data, ".//vig:mfrContact/vig:telephone") or "REVIEW_REQUIRED")
    append_text(mfr_details, "mfrEmailAddress", select_text(payload_data, ".//vig:mfrContact/vig:electronicMail") or "noreply@example.com")

    append_text(admin_info, "mfrRef", select_text(dossier, "./vigbase:Fields/vig:mfr") or "REVIEW_REQUIRED")

    # Optional "other MIR/FSCA reference numbers" (MIR 7.3.1, section 1.3 submitter info).
    # XSD requires them to appear after `mfrRef` in sequence order.

    # other MIR (multi-device) reference numbers
    append_text(admin_info, "ncaRefMultiDev", primary_nca_ref)
    for li_val in nca_ref_multi_values:
        append_text(admin_info, "ncaRefMultiDevLI", li_val)

    # No explicit EUDAMED-only IDs are present for these list entries in the samples we map.
    # We reuse the closest available reference value as a best-effort heuristic.
    append_text(admin_info, "eudamedRefMultiDev", primary_nca_ref)
    for li_val in nca_ref_multi_values:
        append_text(admin_info, "eudamedRefMultiDevLI", li_val)

    append_text(admin_info, "mfrRefMultiDev", primary_mfr_ref)
    for li_val in mfr_ref_multi_values:
        append_text(admin_info, "mfrRefMultiDevLI", li_val)

    # FSCA reference numbers
    primary_nca_fsca = nca_fsca_values[0] if nca_fsca_values else None
    primary_mfr_fsca = mfr_fsca_values[0] if mfr_fsca_values else None

    append_text(admin_info, "ncaRefFSCA", primary_nca_fsca)
    for li_val in nca_fsca_values:
        append_text(admin_info, "ncaRefFSCALI", li_val)

    append_text(admin_info, "eudamedRefFSCA", primary_nca_fsca)
    for li_val in nca_fsca_values:
        append_text(admin_info, "eudamedRefFSCALI", li_val)

    append_text(admin_info, "mfrRefFSCA", primary_mfr_fsca)
    for li_val in mfr_fsca_values:
        append_text(admin_info, "mfrRefFSCALI", li_val)

    # PSR and PMCF/PMPF investigation info (optional)
    psr_primary = psr_id_values[0] if psr_id_values else None
    append_text(admin_info, "psrId", psr_primary)
    for li_val in psr_id_values:
        append_text(admin_info, "psrIdLI", li_val)

    append_text(admin_info, "pmcfpmpfQuestion", pmcf_question)
    primary_pmc = pmcf_pmpf_id_values[0] if pmcf_pmpf_id_values else None
    append_text(admin_info, "pmcfpmpfId", primary_pmc)
    for li_val in pmcf_pmpf_id_values:
        append_text(admin_info, "pmcfpmpfIdLI", li_val)

    device_info = etree.SubElement(incident, "device_info")

    # device_infoT sequence order in MIR 7.3.1 XSD:
    # udiDI, udiDI_Entity, udiPI, udiDIBasic, Basic_Entity, udiDIUnitUse, UnitofUse_Entity,
    # nomenclatureSystem, nomenclatureSystemOther, nomenclatureCode, brandName,
    # deviceDescription, deviceNomenclature, modelNum, catalogNum, serialNum, batchNum,
    # deviceSoftwareVer, deviceFirmwareVer, deviceMfrDate, deviceExpiryDate,
    # ImplantedDateFrom, ImplantedDateTo, ExplantedDateFrom, ExplantedDateTo,
    # implantDuration, implantFacilityName, explantFacilityName,
    # nbIdNum, nbCertNum, nbCertNumLI, nbIdNum2, nbCertNum2, nbCertNum2LI,
    # deviceMarketDateType, deviceMarketDate, AppLegislationUnknown, deviceClass, deviceClassMDD,
    # deviceClassIVDD, deviceClassMDR, deviceClassMDRType, deviceClassIVDR, deviceClassIVDRType,
    # DevicePlacedMarket, DeviceFulfill, CompetentAuthName, RelevantName,
    # distribution, deviceAccessories, deviceAssociated.
    # Keep relative ordering when populating optional fields.

    udi_di = (
        select_text(payload_data, ".//vig:deviceUUID//vigbase:udiDiCode")
        or select_text(payload_data, ".//vig:deviceUUID//vigbase:udiDiCode")
        or select_text(payload_data, ".//vig:deviceUUID/vigbase:deviceIdentifier/vigbase:udiDiCode")
        or select_text(payload_data, ".//vig:deviceIdentification/vigbase:udiDiCode")
        or select_text(payload_data, ".//vigbase:udiDiCode")
        or "REVIEW_REQUIRED"
    )
    append_text(device_info, "udiDI", udi_di)

    udi_pi = (
        select_text(payload_data, ".//vig:udiPISection/vig:udiPIvalue")
        or "REVIEW_REQUIRED"
    )
    append_text(device_info, "udiPI", udi_pi)

    nomenclature_code = (
        select_text(payload_data, ".//vig:deviceInformationSubHead/vig:deviceNomenclatureCode")
        or select_text(payload_data, ".//vig:deviceNomenclatureCodeSelected")
        or "REVIEW_REQUIRED"
    )
    append_text(device_info, "nomenclatureCode", nomenclature_code)
    append_text(device_info, "brandName", brand_or_nomenclature)
    device_description = (
        select_text(payload_data, ".//vig:incidentInformationSection/vig:natureOfIncident")
        or select_text(payload_data, ".//vig:fsnFurtherAdvice")
        or select_text(payload_data, ".//vig:deviceDescriptionAndPurpose")
        or "REVIEW_REQUIRED"
    )
    append_text(device_info, "deviceDescription", device_description)
    append_text(device_info, "deviceNomenclature", brand_or_nomenclature)

    serial_num = select_text(payload_data, ".//vig:udiPISection/vig:affectedSerialNo") or "REVIEW_REQUIRED"
    batch_num = select_text(payload_data, ".//vig:udiPISection/vig:affectedLotNo") or "REVIEW_REQUIRED"
    device_sw_ver = select_text(payload_data, ".//vig:udiPISection/vig:affectedSoftwareNo") or "REVIEW_REQUIRED"
    device_fw_ver = select_text(payload_data, ".//vig:udiPISection/vig:affectedFirmwareNo") or "REVIEW_REQUIRED"
    append_text(device_info, "serialNum", serial_num)
    append_text(device_info, "batchNum", batch_num)
    append_text(device_info, "deviceSoftwareVer", device_sw_ver)
    append_text(device_info, "deviceFirmwareVer", device_fw_ver)

    device_mfr_date = iso_date(select_text(payload_data, ".//vig:udiPISection/vig:affectedDeviceManufacturingDate")) or "1970-01-01"
    device_exp_date = iso_date(select_text(payload_data, ".//vig:udiPISection/vig:affectedDeviceExpiryDate")) or "1970-01-01"
    append_text(device_info, "deviceMfrDate", device_mfr_date)
    append_text(device_info, "deviceExpiryDate", device_exp_date)

    # UDI / certificate identifiers (nb* / certificateNumber) are used in the MIR schema as NB IDs.
    nb_numbers = select_all_texts(payload_data, ".//vig:nbNumber")
    cert_numbers = select_all_texts(payload_data, ".//vig:certificateNumber")

    primary_nb = nb_numbers[0] if nb_numbers else None
    primary_cert = cert_numbers[0] if cert_numbers else None
    append_text(device_info, "nbIdNum", primary_nb)
    append_text(device_info, "nbCertNum", primary_cert)
    for cert in cert_numbers:
        append_text(device_info, "nbCertNumLI", cert)

    nb2 = nb_numbers[1] if len(nb_numbers) > 1 else None
    cert2 = cert_numbers[1] if len(cert_numbers) > 1 else None
    append_text(device_info, "nbIdNum2", nb2)
    append_text(device_info, "nbCertNum2", cert2)
    for cert in cert_numbers[1:]:
        append_text(device_info, "nbCertNum2LI", cert)

    # Market distribution + accessories (available in the provided samples).
    distribution = etree.SubElement(device_info, "distribution")

    dist_codes = select_all_texts(payload_data, ".//vig:marketDistribution/vig:distributionCountry")
    for code in dist_codes:
        append_text(distribution, "distributionEEA", code)

    other_countries = select_all_texts(payload_data, ".//vig:marketDistribution/vig:otherCountries")
    if other_countries:
        append_text(distribution, "otherCountries", other_countries[0])
        for code in other_countries[1:]:
            append_text(distribution, "otherCountriesLI", code)
    # Other distribution fields (distribution_all, etc.) are optional and left out.

    append_text(
        device_info,
        "deviceAccessories",
        select_text(payload_data, ".//vig:associatedDevicesorAccessoriesSection/vig:useOfAccessories") or "",
    )
    append_text(
        device_info,
        "deviceAssociated",
        select_text(payload_data, ".//vig:associatedDevicesorAccessoriesSection/vig:otherAssociatedDevices") or "",
    )

    incident_info = etree.SubElement(incident, "incident_info")
    clinical_event_info = etree.SubElement(incident_info, "clinical_event_info")

    append_text(clinical_event_info, "eventDescription", device_description or "REVIEW_REQUIRED")
    append_text(clinical_event_info, "imdrfCodeChoice1", "UNK")
    append_text(clinical_event_info, "currentDeviceLocation", "Unknown")

    patient_info = etree.SubElement(incident_info, "patient_info")
    append_text(patient_info, "imdrfClinicalCodeChoice1", "UNK")
    append_text(patient_info, "imdrfHealthCodeChoice1", "UNK")
    patient_gender_raw = select_text(payload_data, ".//vig:clinicalInformation/vig:patientGender")
    append_text(
        patient_info,
        "Gender",
        GENDER_MAP.get(patient_gender_raw or "", "Unknown"),
    )
    # massKG / heightCM are integers in the output schema.
    patient_mass = select_text(payload_data, ".//vig:clinicalInformation/vig:patientWeight") or "0"
    patient_height = select_text(payload_data, ".//vig:clinicalInformation/vig:patientHeight") or "0"
    append_text(patient_info, "massKG", patient_mass)
    append_text(patient_info, "heightCM", patient_height)
    append_text(
        patient_info,
        "patientPriorMedication",
        select_text(payload_data, ".//vig:clinicalInformation/vig:patientHealthConditions") or "REVIEW_REQUIRED",
    )

    initial_reporter_info = etree.SubElement(incident_info, "initial_reporter_info")

    reporter_role_raw = select_text(payload_data, ".//vig:initialReporter/vig:initialReporterRole") or "OTHER"
    append_text(initial_reporter_info, "initialReporterRole", INITIAL_REPORTER_ROLE_MAP.get(reporter_role_raw, "Other"))

    # Only include these when present; output schema may treat them as optional.
    append_text(initial_reporter_info, "initialReporterRoleOther", select_text(payload_data, ".//vig:initialReporter/vig:initialReporterOtherRole"))
    append_text(initial_reporter_info, "healthcareFacilityName", select_text(payload_data, ".//vig:initialReporter/vig:healthcareFacilityName") or "REVIEW_REQUIRED")
    append_text(initial_reporter_info, "healthcareFacilityRepNum", select_text(payload_data, ".//vig:initialReporter/vig:healthcareFacilityNumber") or "REVIEW_REQUIRED")
    append_text(initial_reporter_info, "healthcareFacilityCountry", "MT")

    mfr_invest = etree.SubElement(incident, "mfr_invest")
    prelim = select_text(payload_data, ".//vig:manufacturersAnalysis/vig:causeInvestigationConclusions") or "Not provided"
    initial_correction = (
        select_text(payload_data, ".//vig:manufacturersAnalysis/vig:furtherInvestigations")
        or prelim
        or "Not provided"
    )
    append_text(mfr_invest, "manufacturersPrelimAnalysis", prelim)
    append_text(mfr_invest, "manufacturersInitialCorrecAction", initial_correction)
    append_text(mfr_invest, "furtherInvestigations", select_text(payload_data, ".//vig:manufacturersAnalysis/vig:furtherInvestigations") or "Not provided")
    append_text(mfr_invest, "manufacturersFinalComments", prelim)

    result_tree = etree.ElementTree(incident)
    if full_template:
        result_tree = to_full_template(result_tree, report_type_raw)

    if validate:
        ensure_xsd_compliant(result_tree, report_type_raw)
    return result_tree


def main() -> int:
    args = parse_args()
    # Strip invalid XML comments from attribute values in EUDAMED sample files
    raw = args.source.read_bytes()
    cleaned = re.sub(rb"<!--.*?-->", b"", raw, flags=re.DOTALL)
    source_tree = etree.parse(io.BytesIO(cleaned))
    target_tree = build_tree(source_tree, full_template=args.full_template, validate=True)
    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_bytes(etree.tostring(target_tree, pretty_print=True, xml_declaration=True, encoding="UTF-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

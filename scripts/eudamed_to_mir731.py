from __future__ import annotations

import argparse
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lxml import etree

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert EUDAMED MIR to MIR 7.3.1 draft XML")
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
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


def ensure_supported(root: etree._Element) -> None:
    service_id = select_text(root, "./message:recipient/message:service/service:serviceID")
    payload_type = select_text(root, "./message:payload/vigbase:Dossier/vigbase:Data/@xsi:type")
    if service_id != "VIG_DOSSIER" or payload_type != "vig:mir_2Type":
        raise ValueError(f"Unsupported payload: service_id={service_id!r}, payload_type={payload_type!r}")


def build_tree(source_tree: etree._ElementTree) -> etree._ElementTree:
    root = source_tree.getroot()
    ensure_supported(root)

    dossier = root.xpath("./message:payload/vigbase:Dossier", namespaces=NS)[0]
    mir = dossier.xpath("./vigbase:Data/vig:mir_2", namespaces=NS)[0]

    report_type_raw = select_text(mir, "./vig:administrativeInformation/vig:adminInfoSection/vig:reportType") or "INITIAL"
    event_class_raw = select_text(mir, "./vig:administrativeInformation/vig:dateOfIncidentSection/vig:eventClassification") or "DEATH"

    now_date = datetime.now(timezone.utc).date().isoformat()
    brand_or_nomenclature = (
        select_text(mir, ".//vig:deviceInformationSubHead/vig:deviceNomenclatureDescription_manual")
        or select_text(mir, ".//vig:deviceInformationSubHead/vig:deviceNomenclatureDescription")
        or "REVIEW_REQUIRED"
    )

    incident = etree.Element(
        "incident",
        version="7.3.1",
        sCreateTimeStamp=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        sFormLanguage="en",
    )

    admin_info = etree.SubElement(incident, "admin_info")
    append_text(admin_info, "formVersion", "7.3.1")
    append_text(admin_info, "ncaName", select_text(dossier, "./vigbase:Fields/vig:ca_srn") or "REVIEW_REQUIRED")
    append_text(admin_info, "ncaReportNo", select_text(mir, "./vig:administrativeInformation/vig:adminInfoSection/vig:ncaReportRef"))
    append_text(admin_info, "reportDate", now_date)
    append_text(admin_info, "adverseEventDateFrom", iso_date(select_text(mir, "./vig:administrativeInformation/vig:dateOfIncidentSection/vig:startDateofIncident")))
    append_text(admin_info, "adverseEventDateTo", iso_date(select_text(mir, "./vig:administrativeInformation/vig:dateOfIncidentSection/vig:endDateofIncident")))
    append_text(admin_info, "mfrAwarenessDate", iso_date(select_text(mir, "./vig:administrativeInformation/vig:dateOfIncidentSection/vig:mfAwarenessDate")))
    append_text(admin_info, "mfrAwarenessReportDate", iso_date(select_text(mir, "./vig:administrativeInformation/vig:dateOfIncidentSection/vig:mfAwarenessDateReportability")))
    append_text(admin_info, "reportType", REPORT_TYPE_MAP.get(report_type_raw, "Initial"))
    append_text(admin_info, "reportNextDate", iso_date(select_text(mir, "./vig:administrativeInformation/vig:dateOfIncidentSection/vig:reportNextDate")) or now_date)
    append_text(admin_info, "eventClassification", EVENT_CLASSIFICATION_MAP.get(event_class_raw, "Death"))

    contact_info = etree.SubElement(admin_info, "contact_info")
    reporter_mfr = etree.SubElement(contact_info, "reporterMfr")
    append_text(reporter_mfr, "statusReporter", "Manufacturer")
    mfr_details = etree.SubElement(reporter_mfr, "mfrDetails")
    append_text(mfr_details, "mfrName", select_text(dossier, "./vigbase:Fields/vig:mf_srn") or "REVIEW_REQUIRED")
    append_text(mfr_details, "mfrSRN", select_text(dossier, "./vigbase:Fields/vig:mf_srn") or "REVIEW_REQUIRED")
    append_text(mfr_details, "mfrContactPersonFirstName", select_text(mir, ".//vig:mfrContact/vig:firstName") or "REVIEW_REQUIRED")
    append_text(mfr_details, "mfrContactPersonSecondName", select_text(mir, ".//vig:mfrContact/vig:familyName") or "REVIEW_REQUIRED")
    append_text(mfr_details, "mfrCity", "REVIEW_REQUIRED")
    append_text(mfr_details, "mfrCountry", "MT")
    append_text(mfr_details, "mfrPostcode", "REVIEW_REQUIRED")
    append_text(mfr_details, "mfrPhone", select_text(mir, ".//vig:mfrContact/vig:telephone") or "REVIEW_REQUIRED")
    append_text(mfr_details, "mfrEmailAddress", select_text(mir, ".//vig:mfrContact/vig:electronicMail") or "review_required@example.com")

    append_text(admin_info, "mfrRef", select_text(dossier, "./vigbase:Fields/vig:mfr") or "REVIEW_REQUIRED")

    device_info = etree.SubElement(incident, "device_info")
    append_text(device_info, "udiDI", select_text(mir, ".//vig:deviceUUID/vigbase:udiDiCode"))
    append_text(device_info, "udiPI", select_text(mir, ".//vig:udiPISection/vig:udiPIvalue"))
    append_text(device_info, "nomenclatureCode", select_text(mir, ".//vig:deviceInformationSubHead/vig:deviceNomenclatureCode"))
    append_text(device_info, "brandName", brand_or_nomenclature)
    append_text(device_info, "deviceDescription", select_text(mir, ".//vig:incidentInformationSection/vig:natureOfIncident") or "REVIEW_REQUIRED")
    append_text(device_info, "deviceNomenclature", brand_or_nomenclature)
    append_text(device_info, "serialNum", select_text(mir, ".//vig:udiPISection/vig:affectedSerialNo"))
    append_text(device_info, "batchNum", select_text(mir, ".//vig:udiPISection/vig:affectedLotNo"))
    append_text(device_info, "deviceSoftwareVer", select_text(mir, ".//vig:udiPISection/vig:affectedSoftwareNo"))
    append_text(device_info, "deviceFirmwareVer", select_text(mir, ".//vig:udiPISection/vig:affectedFirmwareNo"))
    append_text(device_info, "deviceMfrDate", iso_date(select_text(mir, ".//vig:udiPISection/vig:affectedDeviceManufacturingDate")))
    append_text(device_info, "deviceExpiryDate", iso_date(select_text(mir, ".//vig:udiPISection/vig:affectedDeviceExpiryDate")))

    incident_info = etree.SubElement(incident, "incident_info")
    clinical_event_info = etree.SubElement(incident_info, "clinical_event_info")
    append_text(clinical_event_info, "eventDescription", select_text(mir, ".//vig:incidentInformationSection/vig:natureOfIncident") or "REVIEW_REQUIRED")
    append_text(clinical_event_info, "imdrfCodeChoice1", "UNK")
    append_text(clinical_event_info, "currentDeviceLocation", "Unknown")

    patient_info = etree.SubElement(incident_info, "patient_info")
    append_text(patient_info, "imdrfClinicalCodeChoice1", "UNK")
    append_text(patient_info, "imdrfHealthCodeChoice1", "UNK")
    append_text(patient_info, "Gender", GENDER_MAP.get(select_text(mir, ".//vig:clinicalInformation/vig:patientGender") or "", "Unknown"))
    append_text(patient_info, "massKG", select_text(mir, ".//vig:clinicalInformation/vig:patientWeight"))
    append_text(patient_info, "heightCM", select_text(mir, ".//vig:clinicalInformation/vig:patientHeight"))
    append_text(patient_info, "patientPriorMedication", select_text(mir, ".//vig:clinicalInformation/vig:patientHealthConditions"))

    initial_reporter_info = etree.SubElement(incident_info, "initial_reporter_info")
    reporter_role_raw = select_text(mir, ".//vig:initialReporter/vig:initialReporterRole") or "OTHER"
    append_text(initial_reporter_info, "initialReporterRole", INITIAL_REPORTER_ROLE_MAP.get(reporter_role_raw, "Other"))
    append_text(initial_reporter_info, "initialReporterRoleOther", select_text(mir, ".//vig:initialReporter/vig:initialReporterOtherRole"))
    append_text(initial_reporter_info, "healthcareFacilityName", select_text(mir, ".//vig:initialReporter/vig:healthcareFacilityName"))
    append_text(initial_reporter_info, "healthcareFacilityRepNum", select_text(mir, ".//vig:initialReporter/vig:healthcareFacilityNumber"))
    append_text(initial_reporter_info, "healthcareFacilityCountry", "MT")

    mfr_invest = etree.SubElement(incident, "mfr_invest")
    append_text(mfr_invest, "manufacturersPrelimAnalysis", select_text(mir, ".//vig:manufacturersAnalysis/vig:causeInvestigationConclusions") or "REVIEW_REQUIRED")
    append_text(mfr_invest, "manufacturersInitialCorrecAction", "REVIEW_REQUIRED")
    append_text(mfr_invest, "furtherInvestigations", select_text(mir, ".//vig:manufacturersAnalysis/vig:furtherInvestigations") or "REVIEW_REQUIRED")
    append_text(mfr_invest, "manufacturersFinalComments", select_text(mir, ".//vig:manufacturersAnalysis/vig:causeInvestigationConclusions"))

    return etree.ElementTree(incident)


def main() -> int:
    args = parse_args()
    # Strip invalid XML comments from attribute values in EUDAMED sample files
    raw = args.source.read_bytes()
    cleaned = re.sub(rb"<!--.*?-->", b"", raw, flags=re.DOTALL)
    source_tree = etree.parse(io.BytesIO(cleaned))
    target_tree = build_tree(source_tree)
    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_bytes(etree.tostring(target_tree, pretty_print=True, xml_declaration=True, encoding="UTF-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

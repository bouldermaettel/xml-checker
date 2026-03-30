from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from lxml import etree

XSD_NS = {"xsd": "http://www.w3.org/2001/XMLSchema"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an XML template from an XSD schema.")
    parser.add_argument("xsd", type=Path, help="Path to XSD file")
    parser.add_argument("output", type=Path, help="Path to output XML file")
    return parser.parse_args()


def local_type_name(type_name: Optional[str]) -> Optional[str]:
    if not type_name:
        return None
    return type_name.split(":", 1)[-1]


def first_enum(simple_type: etree._Element) -> Optional[str]:
    enums = simple_type.xpath("./xsd:restriction/xsd:enumeration/@value", namespaces=XSD_NS)
    return enums[0] if enums else None


def facet_value(restriction: etree._Element, facet_name: str) -> Optional[str]:
    facet = restriction.find(f"./xsd:{facet_name}", namespaces=XSD_NS)
    if facet is None:
        return None
    return facet.get("value")


def first_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def first_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def placeholder_for_simple_type(simple_type: etree._Element) -> str:
    enum_value = first_enum(simple_type)
    if enum_value is not None:
        return enum_value

    restriction = simple_type.find("./xsd:restriction", namespaces=XSD_NS)
    if restriction is None:
        return "X"

    base = local_type_name(restriction.get("base"))
    pattern = restriction.find("./xsd:pattern", namespaces=XSD_NS)
    pattern_value = pattern.get("value") if pattern is not None else None

    if base in ("date",):
        return "1970-01-01"
    if base in ("dateTime",):
        return "1970-01-01T00:00:00+00:00"

    if base in ("integer", "int", "long", "short", "decimal"):
        min_inclusive = first_float(facet_value(restriction, "minInclusive"))
        min_exclusive = first_float(facet_value(restriction, "minExclusive"))
        max_inclusive = first_float(facet_value(restriction, "maxInclusive"))
        max_exclusive = first_float(facet_value(restriction, "maxExclusive"))

        if pattern_value and "0-9" in pattern_value:
            return "1"

        candidate = 1.0
        if min_inclusive is not None:
            candidate = min_inclusive
        elif min_exclusive is not None:
            candidate = min_exclusive + 1

        if max_inclusive is not None and candidate > max_inclusive:
            candidate = max_inclusive
        if max_exclusive is not None and candidate >= max_exclusive:
            candidate = max_exclusive - 1

        return str(max(0, int(candidate)))

    if base in ("string", "normalizedString", "token"):
        if pattern_value and "0-9" in pattern_value:
            return "1"

        length = first_int(facet_value(restriction, "length"))
        min_length = first_int(facet_value(restriction, "minLength"))
        max_length = first_int(facet_value(restriction, "maxLength"))

        if length is not None:
            n = max(1, length)
        else:
            n = max(1, min_length or 1)
            if max_length is not None:
                n = min(n, max_length)

        return "X" * n

    return "X"


def placeholder_for_type(type_name: Optional[str], simple_types: dict[str, etree._Element]) -> str:
    base = local_type_name(type_name)
    if base in ("date",):
        return "1970-01-01"
    if base in ("dateTime",):
        return "1970-01-01T00:00:00+00:00"
    if base in ("integer", "int", "long", "short", "decimal"):
        return "0"
    if base in simple_types:
        return placeholder_for_simple_type(simple_types[base])
    return "X"


def build_element(
    element_def: etree._Element,
    complex_types: dict[str, etree._Element],
    simple_types: dict[str, etree._Element],
) -> etree._Element:
    name = element_def.get("name")
    if not name:
        # For unsupported anonymous refs, keep a stable marker.
        name = "unnamedElement"
    elem = etree.Element(name)

    inline_complex = element_def.find("./xsd:complexType", namespaces=XSD_NS)
    if inline_complex is not None:
        fill_complex(elem, inline_complex, complex_types, simple_types)
        return elem

    type_name = local_type_name(element_def.get("type"))
    if type_name and type_name in complex_types:
        fill_complex(elem, complex_types[type_name], complex_types, simple_types)
        return elem

    elem.text = placeholder_for_type(element_def.get("type"), simple_types)
    return elem


def fill_complex(
    target: etree._Element,
    complex_type: etree._Element,
    complex_types: dict[str, etree._Element],
    simple_types: dict[str, etree._Element],
) -> None:
    sequence = complex_type.find("./xsd:sequence", namespaces=XSD_NS)
    if sequence is not None:
        for child in sequence:
            if not isinstance(child.tag, str):
                continue
            child_name = etree.QName(child).localname
            if child_name == "element":
                target.append(build_element(child, complex_types, simple_types))
            elif child_name == "choice":
                # Emit the first choice branch for a deterministic template.
                first_choice = child.find("./xsd:element", namespaces=XSD_NS)
                if first_choice is not None:
                    target.append(build_element(first_choice, complex_types, simple_types))

    choice = complex_type.find("./xsd:choice", namespaces=XSD_NS)
    if choice is not None:
        first_choice = choice.find("./xsd:element", namespaces=XSD_NS)
        if first_choice is not None:
            target.append(build_element(first_choice, complex_types, simple_types))

    for attr in complex_type.findall("./xsd:attribute", namespaces=XSD_NS):
        attr_name = attr.get("name")
        if not attr_name:
            continue
        target.set(attr_name, placeholder_for_type(attr.get("type"), simple_types))


def build_template_tree_from_xsd(xsd_path: Path) -> etree._ElementTree:
    tree = etree.parse(str(xsd_path))
    schema = tree.getroot()

    complex_types = {
        ct.get("name"): ct
        for ct in schema.findall("./xsd:complexType", namespaces=XSD_NS)
        if ct.get("name")
    }
    simple_types = {
        st.get("name"): st
        for st in schema.findall("./xsd:simpleType", namespaces=XSD_NS)
        if st.get("name")
    }

    root_def = schema.find("./xsd:element[@name='incident']", namespaces=XSD_NS)
    if root_def is None:
        raise ValueError("Could not find root xsd:element named 'incident'")

    root_xml = build_element(root_def, complex_types, simple_types)
    return etree.ElementTree(root_xml)


def main() -> int:
    args = parse_args()
    xml_tree = build_template_tree_from_xsd(args.xsd)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(etree.tostring(xml_tree, pretty_print=True, xml_declaration=True, encoding="UTF-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
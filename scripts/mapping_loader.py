import csv
from pathlib import Path
from typing import List, Dict

def load_mapping_table(csv_path: Path) -> List[Dict[str, str]]:
    """
    Load the mapping table from a CSV file.
    Returns a list of dicts with keys: EUDAMED Field Path, MIR Field Path, Mapping Type, Rule/Notes
    """
    with csv_path.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(
            (row for row in f if not row.strip().startswith('#') and row.strip()),
            fieldnames=["EUDAMED Field Path", "MIR Field Path", "Mapping Type", "Rule/Notes"]
        )
        # Skip header
        next(reader)
        return [row for row in reader]

# Example usage:
# mapping = load_mapping_table(Path('scripts/field_mapping_template.csv'))

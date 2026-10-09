import json
from pathlib import Path
from gitshield.core.models import ScanReport, Severity


SARIF_SEVERITY_MAP = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "none",
}


def export_to_sarif(report: ScanReport, output_file: Path) -> None:
    """Generate OASIS SARIF 2.1.0 output compatible with GitHub Code Scanning."""
    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "GitShield",
                        "version": "0.1.0",
                        "informationUri": "https://github.com/AlperEnesErsu/GitShield",
                        "rules": [],
                    }
                },
                "results": [],
            }
        ],
    }

    rules_seen = set()
    driver_rules = sarif["runs"][0]["tool"]["driver"]["rules"]
    results = sarif["runs"][0]["results"]

    for f in report.findings:
        if f.rule_id not in rules_seen:
            rules_seen.add(f.rule_id)
            driver_rules.append(
                {
                    "id": f.rule_id,
                    "shortDescription": {"text": f.title},
                    "fullDescription": {"text": f.description},
                    "defaultConfiguration": {
                        "level": SARIF_SEVERITY_MAP.get(f.severity, "warning")
                    },
                    "help": {"text": f.suggested_fix or ""},
                }
            )

        results.append(
            {
                "ruleId": f.rule_id,
                "level": SARIF_SEVERITY_MAP.get(f.severity, "warning"),
                "message": {"text": f"{f.title}: {f.description}"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": f.file_path},
                            "region": {
                                "startLine": f.line_number,
                                "startColumn": 1,
                            },
                        }
                    }
                ],
            }
        )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as out:
        json.dump(sarif, out, indent=2)

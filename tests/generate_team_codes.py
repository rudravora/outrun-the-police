"""
Generate organizer-friendly team codes for Outrun the Police.

Input CSV:
    team_name
    Alpha
    Beta
    Gamma

Usage:
    python generate_team_codes.py --input registered_teams.csv --output team_codes.csv

The input may contain additional columns; they are preserved in the output and
the generated team_code column is appended.

Codes use only characters that are easy to read aloud and visually distinguish.
"""

import argparse
import csv
import secrets
from pathlib import Path


ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def generate_code(existing_codes):
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        if code not in existing_codes:
            return code


def generate_team_codes(input_path, output_path):
    input_path = Path(input_path)
    output_path = Path(output_path)

    with input_path.open("r", newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)

        if not reader.fieldnames:
            raise ValueError("Input CSV has no header row.")

        if "team_name" not in reader.fieldnames:
            raise ValueError(
                "Input CSV must contain a 'team_name' column."
            )

        rows = list(reader)

    if not rows:
        raise ValueError("Input CSV contains no teams.")

    existing_names = set()
    for row in rows:
        name = (row.get("team_name") or "").strip()
        if not name:
            raise ValueError("Every team must have a non-empty team_name.")
        if name in existing_names:
            raise ValueError(f"Duplicate team_name found: {name}")
        existing_names.add(name)

    existing_codes = set()

    for row in rows:
        row["team_code"] = generate_code(existing_codes)
        existing_codes.add(row["team_code"])

    fieldnames = list(reader.fieldnames)
    if "team_code" not in fieldnames:
        fieldnames.append("team_code")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # utf-8-sig opens cleanly in Excel on Windows while remaining valid CSV.
    with output_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Generate unique team codes from a registered-teams CSV."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="CSV containing a required team_name column.",
    )
    parser.add_argument(
        "--output",
        default="team_codes.csv",
        help="Output CSV path.",
    )
    args = parser.parse_args()

    count = generate_team_codes(args.input, args.output)
    print(f"Generated {count} team codes.")
    print(f"Output: {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()

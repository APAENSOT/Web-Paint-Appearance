"""Runtime-only fixture bytes; reuse T04's approved columns and values without importing its tests."""
import ast
import io
import sys
from pathlib import Path

from openpyxl import Workbook

source = Path(__file__).resolve().parents[2] / "backend/tests/test_t04_ingest.py"
constants = {}
for statement in ast.parse(source.read_text(encoding="utf-8")).body:
    if isinstance(statement, ast.Assign):
        for target in statement.targets:
            if isinstance(target, ast.Name) and target.id in {"HEADERS", "BASE_ROW"}:
                constants[target.id] = ast.literal_eval(statement.value)

workbook = Workbook()
for index in range(int(sys.argv[2])):
    sheet = workbook.active if index == 0 else workbook.create_sheet()
    sheet.title = f"Review{index + 1}"
    headers = list(constants["HEADERS"])
    if len(sys.argv) > 4:
        headers[headers.index("Checkzone")] = sys.argv[4]
    sheet.append(headers)
    row = {**constants["BASE_ROW"], "Serial No": f"{sys.argv[1]}-{index + 1}"}
    if len(sys.argv) > 3:
        row["Plant"] = sys.argv[3]
    sheet.append([row[header] for header in constants["HEADERS"]])
buffer = io.BytesIO()
workbook.save(buffer)
sys.stdout.buffer.write(buffer.getvalue())

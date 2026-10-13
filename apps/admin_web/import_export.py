"""Reusable CSV/XLSX import and export helpers for admin web and API callers."""
import csv
import io
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree as ET


def read_xlsx(uploaded):
    with ZipFile(uploaded) as book:
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()) for node in root.findall("m:si", ns)]
        sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
        rows = []
        for row in sheet.findall("m:sheetData/m:row", ns):
            values = {}
            for cell in row.findall("m:c", ns):
                ref = cell.attrib.get("r", "A1")
                col = 0
                for char in ref:
                    if char.isalpha():
                        col = col * 26 + ord(char.upper()) - 64
                    else:
                        break
                value = cell.find("m:v", ns)
                text = "" if value is None else value.text or ""
                if cell.attrib.get("t") == "s" and text:
                    text = shared[int(text)]
                values[col - 1] = text
            rows.append([values.get(i, "") for i in range(max(values.keys(), default=-1) + 1)])
        return rows


def read_rows(uploaded):
    name = uploaded.name.lower()
    if name.endswith(".xlsx"):
        rows = read_xlsx(uploaded)
    elif name.endswith(".csv"):
        rows = list(csv.reader(io.TextIOWrapper(uploaded, encoding="utf-8-sig")))
    else:
        raise ValueError("Only .csv and .xlsx files are supported.")
    if not rows:
        raise ValueError("The uploaded file is empty.")
    headers = [str(value).strip().lower() for value in rows[0]]
    return [dict(zip(headers, row)) for row in rows[1:] if any(str(value).strip() for value in row)]


def make_xlsx(headers, data):
    def cell(value, row, col):
        ref, number = "", col + 1
        while number:
            number, remainder = divmod(number - 1, 26)
            ref = chr(65 + remainder) + ref
        text = str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<c r="{ref}{row}" t="inlineStr"><is><t>{text}</t></is></c>'
    rows = [headers] + data
    xml_rows = "".join(f'<row r="{i}">' + "".join(cell(v, i, j) for j, v in enumerate(row)) + "</row>" for i, row in enumerate(rows, 1))
    files = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Students" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{xml_rows}</sheetData></worksheet>',
    }
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()

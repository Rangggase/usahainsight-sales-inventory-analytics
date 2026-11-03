"""CSV and Excel exports (sanitize untrusted text for spreadsheet formulas)."""
from io import BytesIO, StringIO
import csv

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from app.services.analytics import report_lines, inventory_rows

COLUMNS = ("transaction_id", "date", "sku", "product", "category", "quantity", "unit_price", "line_total")


def safe_text(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def sales_csv(start=None, end=None):
    data = report_lines(start, end)
    output = StringIO()
    output.write("\ufeff")  # Excel-compatible UTF-8 BOM
    writer = csv.writer(output)
    writer.writerow(COLUMNS)
    for row in data:
        writer.writerow([safe_text(row[k]) for k in COLUMNS])
    return output.getvalue().encode("utf-8")


def sales_xlsx(start=None, end=None):
    rows = report_lines(start, end)
    book = Workbook()
    ws = book.active
    ws.title = "Penjualan"
    ws.append(list(COLUMNS))
    for row in rows:
        ws.append([safe_text(row[k]) for k in COLUMNS])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.column_dimensions["D"].width = 28
    ws.column_dimensions["E"].width = 20
    for col in ("A", "B", "C"):
        ws.column_dimensions[col].width = 20
    for col in ("F", "G", "H"):
        ws.column_dimensions[col].width = 18
    for cells in ws.iter_cols(min_col=7, max_col=8, min_row=2):
        for cell in cells:
            cell.number_format = '"Rp" #,##0'

    stock = book.create_sheet("Persediaan")
    stock.append(["SKU", "Produk", "Kategori", "Stok", "Stok Minimum", "Status"])
    for r in inventory_rows():
        stock.append([safe_text(r["sku"]), safe_text(r["name"]), safe_text(r["category"]),
                      r["current_stock"], r["min_stock"], r["status"]])
    stock.freeze_panes = "A2"
    stock.auto_filter.ref = stock.dimensions
    stock.column_dimensions["B"].width = 30
    stock.column_dimensions["C"].width = 20
    for col in ("A", "D", "E", "F"):
        stock.column_dimensions[col].width = 18

    summary = book.create_sheet("Ringkasan", 0)
    summary.append(["Metrik", "Nilai"])
    summary.append(["Periode awal", start or "Semua tanggal"])
    summary.append(["Periode akhir", end or "Semua tanggal"])
    summary.append(["Total omzet", sum(r["line_total"] for r in rows)])
    summary.append(["Total unit terjual", sum(r["quantity"] for r in rows)])
    summary.append(["Total transaksi", len({r["transaction_id"] for r in rows})])
    summary.column_dimensions["A"].width = 26
    summary.column_dimensions["B"].width = 25
    summary["B4"].number_format = '"Rp" #,##0'

    for sheet in book:
        sheet.sheet_view.showGridLines = False
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor="16324F")
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(vertical="center")
        sheet.row_dimensions[1].height = 25
    file = BytesIO()
    book.save(file)
    return file.getvalue()

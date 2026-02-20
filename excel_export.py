"""
Экспорт данных паспортов в Excel
"""
import os
from pathlib import Path

from openpyxl import load_workbook, Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

from ocr_extractor import EXCEL_COLUMNS


def _get_columns_from_template(template_path: str) -> list[str] | None:
    """Загрузить заголовки колонок из эталонного Excel"""
    if not os.path.exists(template_path):
        return None
    try:
        wb = load_workbook(template_path, read_only=True, data_only=True)
        ws = wb.active
        headers = [cell.value for cell in ws[1] if cell.value]
        wb.close()
        return headers if headers else None
    except Exception:
        return None


def create_excel(
    data: list[dict],
    output_path: str,
    template_excel: str | None = None,
) -> str:
    """
    Создать Excel-файл с данными паспортов в формате как в эталоне
    """
    columns = _get_columns_from_template(template_excel) if template_excel else None
    columns = columns or EXCEL_COLUMNS

    wb = Workbook()
    ws = wb.active
    ws.title = "Паспорта"

    # Заголовки
    for col_idx, header in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", wrap_text=True)

    # Данные
    for row_idx, row_data in enumerate(data, start=2):
        for col_idx, col_name in enumerate(columns, 1):
            value = row_data.get(col_name, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    # Автоширина колонок — Кем выдан и Адрес: шире, чтобы текст был виден
    wide_cols = ("Кем выдан", "Адрес регистрации", "Место рождения")
    wide_min = {"Кем выдан": 80, "Адрес регистрации": 60, "Место рождения": 40}
    for col_idx in range(1, len(columns) + 1):
        col_letter = get_column_letter(col_idx)
        col_name = columns[col_idx - 1] if col_idx <= len(columns) else ""
        max_length = max(
            len(str(ws.cell(row=r, column=col_idx).value or ""))
            for r in range(1, len(data) + 2)
        )
        if col_name in wide_cols:
            wmin = wide_min.get(col_name, 60)
            ws.column_dimensions[col_letter].width = min(max(max_length + 2, wmin), 150)
        else:
            ws.column_dimensions[col_letter].width = min(max_length + 2, 50)

    # Рамки
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    for row in ws.iter_rows(
        min_row=1, max_row=len(data) + 1, min_col=1, max_col=len(columns)
    ):
        for cell in row:
            cell.border = thin_border

    output = Path(output_path)
    wb.save(output)
    return str(output)

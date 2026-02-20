"""Debug: show raw OCR and parsed result"""
import os
import sys

# Simulate combined OCR from both pages (main + registration)
# Based on user's actual passport data structure
SAMPLE_OCR = """
Р О С С И Й С К А Я Ф Е Д Е Р А Ц И Я
Паспорт выдан
ТП №84 ОТДЕЛА УФМС РОССИИ ПО
САНКТ-ПЕТЕРБУРГУ И ЛЕНИНГРАДСКОЙ ОБЛ. В
ЦЕНТРАЛЬНОМ Р-НЕ ГОР.САНКТ-ПЕТЕРБУРГА
780-084
Дата выдачи 24.09.2008 Код подразделения
ЦИЦАР
Фамилия
ЦИЦАР
Имя
ФЕДОР
Отчество
МИХАЙЛОВИЧ
МУЖ.
рождения
03.04.1987
ГОР.
ЛЕНИНГРАД
4008 595794
Зарегистрирован 16 августа 1988
Пункт Гор.Санкт-Петербург
Р-н Центральный
Улица Фурштатская ул.
Дом 12 Корп - кв 21
"""

def main():
    from ocr_extractor import parse_passport_data
    data = parse_passport_data(SAMPLE_OCR)
    with open("debug_result.txt", "w", encoding="utf-8") as f:
        for k, v in data.items():
            f.write(f"{k}: {v!r}\n")
    print("Written to debug_result.txt")
    # Проверка: не должны быть "Выдан", "ТП", "77 87"
    assert data.get("Фамилия") == "ЦИЦАР", f"Фамилия: {data.get('Фамилия')}"
    assert data.get("Имя") == "ФЕДОР", f"Имя: {data.get('Имя')}"
    assert data.get("Отчество") == "МИХАЙЛОВИЧ", f"Отчество: {data.get('Отчество')}"
    assert data.get("Серия и номер паспорта") == "40 08 595794", f"Серия: {data.get('Серия и номер паспорта')}"
    assert data.get("Дата рождения") == "03.04.1987", f"Дата рождения: {data.get('Дата рождения')}"
    assert data.get("Дата выдачи") == "24.09.2008", f"Дата выдачи: {data.get('Дата выдачи')}"
    print("OK: all assertions passed")

# OCR с «шумом» — слова Выдан, ТП и ложная серия рядом с ФИО
BAD_OCR = """
Паспорт выдан
ТП №84 ОТДЕЛА УФМС
77 87 3444442073
Фамилия ФЕДОР Имя Выдан Отчество ТП
ЦИЦАР ФЕДОР МИХАЙЛОВИЧ
рождения 03.04.1987
4008 595794
"""

if __name__ == "__main__":
    main()
    # Доп. тест: при плохом порядке строк не должны браться Выдан, ТП, 77 87
    from ocr_extractor import parse_passport_data
    bad_data = parse_passport_data(BAD_OCR)
    assert bad_data.get("Фамилия") != "ФЕДОР", "Фамилия не должна быть ФЕДОР (это имя)"
    assert bad_data.get("Имя") != "Выдан", "Имя не должно быть Выдан"
    assert bad_data.get("Отчество") != "ТП", "Отчество не должно быть ТП"
    assert "77" not in (bad_data.get("Серия и номер паспорта") or ""), "Серия не должна содержать 77 87"
    print("BAD_OCR test: OK")

    # Почество, 84 78, дата без ведущего нуля
    from ocr_extractor import parse_passport_data
    ugly = "ФЕДОРФ Почество МИХАЙЛОВИЧ 84 78 008424 40 08 595794 3.04.1987 24.09.2008\nЦИЦАР\nФЕДОР\nМИХАЙЛОВИЧ"
    u = parse_passport_data(ugly)
    assert u.get("Имя") != "Почество", "Почество не должно быть Именем"
    assert "84" not in (u.get("Серия и номер паспорта") or ""), "Серия не 84 78"
    assert u.get("Дата рождения") == "03.04.1987", f"Дата: {u.get('Дата рождения')}"
    print("UGLY_OCR test: OK")

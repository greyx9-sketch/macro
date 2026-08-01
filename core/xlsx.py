# -*- coding: utf-8 -*-
"""표준 라이브러리만으로 .xlsx/.xlsm 읽기.

openpyxl 을 쓰지 않는 이유: 이 프로젝트는 GitHub Actions 에서 매일 자동 실행되므로
필수 외부 의존성이 적을수록 몇 년 뒤 조용히 깨질 확률이 낮다. 엑셀 임포트는
읽기 전용이고 한 번만 쓰므로 zipfile + ElementTree 로 충분하다.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

# 엑셀 날짜 일련번호의 기준점. 1900년 윤년 버그 때문에 1899-12-30 이다.
EXCEL_EPOCH = date(1899, 12, 30)


@dataclass
class Cell:
    ref: str
    value: Optional[object]   # str | float | None
    is_text: bool             # 공유문자열/인라인문자열에서 왔는가


class Sheet:
    def __init__(self, name: str, cells: dict[str, Cell]):
        self.name = name
        self.cells = cells

    def get(self, ref: str) -> Optional[object]:
        c = self.cells.get(ref)
        return c.value if c else None

    def text(self, ref: str) -> Optional[str]:
        v = self.get(ref)
        return None if v is None else str(v)

    def is_text(self, ref: str) -> bool:
        c = self.cells.get(ref)
        return bool(c and c.is_text)

    def max_row(self) -> int:
        best = 0
        for ref in self.cells:
            row = int("".join(ch for ch in ref if ch.isdigit()) or 0)
            best = max(best, row)
        return best


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    out: list[str] = []
    for si in root.findall("m:si", NS):
        # <si><t>텍스트</t></si> 또는 서식이 섞인 <si><r><t>..</t></r>...</si>
        parts = [t.text or "" for t in si.iter(f"{{{NS['m']}}}t")]
        out.append("".join(parts))
    return out


def _sheet_names(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """[(시트명, 워크시트 XML 경로)] 를 워크북 순서대로."""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))

    rel_map = {
        rel.get("Id"): rel.get("Target")
        for rel in rels.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
    }

    out: list[tuple[str, str]] = []
    for sheet in wb.find("m:sheets", NS).findall("m:sheet", NS):
        name = sheet.get("name")
        rid = sheet.get(f"{{{NS['r']}}}id")
        target = rel_map.get(rid, "")
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = "xl/" + target.lstrip("./")
        out.append((name, path))
    return out


def load(path: Path) -> dict[str, Sheet]:
    sheets: dict[str, Sheet] = {}
    with zipfile.ZipFile(path) as zf:
        strings = _shared_strings(zf)
        for name, xml_path in _sheet_names(zf):
            root = ET.fromstring(zf.read(xml_path))
            cells: dict[str, Cell] = {}
            data = root.find("m:sheetData", NS)
            if data is None:
                sheets[name] = Sheet(name, cells)
                continue
            for row in data.findall("m:row", NS):
                for c in row.findall("m:c", NS):
                    ref = c.get("r")
                    ctype = c.get("t")
                    v_el = c.find("m:v", NS)

                    if ctype == "s":  # 공유 문자열
                        if v_el is None or v_el.text is None:
                            continue
                        idx = int(v_el.text)
                        val: object = strings[idx] if idx < len(strings) else ""
                        cells[ref] = Cell(ref, val, True)
                        continue

                    if ctype == "inlineStr":
                        is_el = c.find("m:is", NS)
                        txt = "".join(t.text or "" for t in is_el.iter(f"{{{NS['m']}}}t")) if is_el is not None else ""
                        cells[ref] = Cell(ref, txt, True)
                        continue

                    if ctype == "str":  # 수식 결과 문자열
                        cells[ref] = Cell(ref, v_el.text if v_el is not None else None, True)
                        continue

                    if v_el is None or v_el.text is None:
                        continue
                    try:
                        cells[ref] = Cell(ref, float(v_el.text), False)
                    except ValueError:
                        cells[ref] = Cell(ref, v_el.text, True)
            sheets[name] = Sheet(name, cells)
    return sheets


def serial_to_date(serial: float) -> date:
    """엑셀 날짜 일련번호를 date 로.

    엑셀 시트에서 발견된 46204 / 46233 / 46240 같은 값이 여기로 온다.
    같은 열에 텍스트 날짜와 일련번호가 섞여 있는 것이 원본의 실제 오류였다.
    """
    return EXCEL_EPOCH + timedelta(days=int(serial))


def col_letters(ref: str) -> str:
    return "".join(ch for ch in ref if ch.isalpha())


def col_index(letters: str) -> int:
    """'A' -> 1, 'Z' -> 26, 'AA' -> 27."""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def index_to_col(index: int) -> str:
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def shift_col(letters: str, delta: int) -> str:
    return index_to_col(col_index(letters) + delta)

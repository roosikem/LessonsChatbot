import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from app import ranking

REPO_DIR = Path(__file__).resolve().parents[2]


@dataclass
class Lesson:
    id: str
    title: str
    text: str
    context: dict[str, list[str]]
    signals: dict = field(default_factory=dict)  # ranking signal values, see app/ranking.py

    def embed_text(self):
        ctx = "; ".join(f"{k}: {', '.join(v)}" for k, v in self.context.items() if v)
        return f"{self.title}\n{self.text}\n{ctx}"

    def to_dict(self):
        return asdict(self)


@dataclass
class ContextItem:
    """One row of a context source (a project, a supplier, a component...)."""
    source: str
    id: str
    name: str
    attrs: dict[str, str]
    text: str

    def key(self, match_on="name"):
        return self.id if match_on == "id" else self.name

    def to_dict(self):
        return asdict(self)


@dataclass
class LoadReport:
    rows: int = 0
    loaded: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)
    unknown_links: dict[str, set] = field(default_factory=dict)  # source -> lesson values with no item

    def summary(self):
        lines = [f"rows: {self.rows}, loaded: {self.loaded}, skipped: {len(self.skipped)}"]
        lines += [f"  skipped {rid}: {why}" for rid, why in self.skipped]
        for source, values in self.unknown_links.items():
            lines.append(f"  lessons point to unknown {source}: {sorted(values)}")
        return "\n".join(lines)


def load_mapping(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_rows(path, delimiter=None, sheet=None, header_row=1, encoding=None):
    path = REPO_DIR / path  # absolute paths (uploads) stay as they are
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return read_excel(path, sheet, header_row)
    text = read_text(path, encoding)
    lines = text.splitlines(keepends=True)[header_row - 1:]
    delimiter = delimiter or sniff_delimiter(lines[0] if lines else "")
    rows = []
    for row in csv.DictReader(lines, delimiter=delimiter):
        # short rows give None, extra cells land under the None key; both would break .strip()
        rows.append({k: (v or "") if isinstance(v, str) or v is None else "" for k, v in row.items() if k is not None})
    return rows


def read_text(path, encoding=None):
    data = Path(path).read_bytes()
    if encoding:
        return data.decode(encoding)
    try:
        return data.decode("utf-8-sig")  # drops the BOM Excel likes to add
    except UnicodeDecodeError:
        return data.decode("cp1252")  # what Excel on Windows writes for "CSV"


def detect_csv(path):
    """Encoding and delimiter of a CSV file, so they can be saved in the mapping."""
    data = Path(REPO_DIR / path).read_bytes()
    try:
        text, encoding = data.decode("utf-8-sig"), "utf-8-sig"
    except UnicodeDecodeError:
        text, encoding = data.decode("cp1252"), "cp1252"
    return encoding, sniff_delimiter(text.split("\n", 1)[0])


def sniff_delimiter(header):
    counts = {d: header.count(d) for d in (",", ";", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def read_excel(path, sheet=None, header_row=1):
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    rows = ws.iter_rows(min_row=header_row, values_only=True)
    header = [str(h).strip() if h is not None else f"column_{i + 1}" for i, h in enumerate(next(rows, []))]
    out = []
    for values in rows:
        if all(v is None or str(v).strip() == "" for v in values):
            continue
        out.append({h: cell_text(v) for h, v in zip(header, values)})
    wb.close()
    return out


def cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))  # 1001.0 -> "1001"
    if hasattr(value, "date") and hasattr(value, "isoformat"):
        return value.date().isoformat() if value.time().isoformat() == "00:00:00" else value.isoformat()
    return str(value).strip()


def split_values(value, sep):
    if not value:
        return []
    if not sep:
        return [value.strip()]
    return [v.strip() for v in value.split(sep) if v.strip()]


def short_title(text, limit=80):
    """A title from the text, for data without a title column."""
    first = text.strip().split("\n")[0]
    first = first.split(". ")[0].rstrip(".")
    return first if len(first) <= limit else first[:limit].rsplit(" ", 1)[0] + "…"


def load_lessons(mapping, report=None, rows=None):
    m = mapping["lessons"]
    report = report or LoadReport()
    multi = m.get("multi_value", {})
    lessons, seen = [], set()
    if rows is None:
        rows = read_rows(m["file"], m.get("delimiter"), m.get("sheet"), m.get("header_row", 1), m.get("encoding"))

    signals = ranking.config(mapping)
    for row in rows:
        report.rows += 1
        lid = (row.get(m["id"]) or "").strip()

        if not lid:
            report.skipped.append((f"data row {report.rows}", "missing id"))
            continue
        failed = [col for col, allowed in m.get("filter", {}).items() if (row.get(col) or "").strip() not in allowed]
        if failed:
            report.skipped.append((lid, f"filtered out by {failed[0]}"))
            continue
        if lid in seen:
            report.skipped.append((lid, "duplicate id"))
            continue

        text = "\n".join((row.get(c) or "").strip() for c in m["text"]).strip()
        if not text:
            report.skipped.append((lid, "empty lesson text"))
            continue

        # sorted, so the embedded text doesn't change with the order values arrive in
        context = {dim: sorted(split_values(row.get(col) or "", multi.get(col))) for dim, col in m["context"].items()}
        lessons.append(Lesson(
            id=lid,
            title=(row.get(m.get("title") or "") or "").strip() or short_title(text),
            text=text,
            context=context,
            signals=ranking.read(row, signals),
        ))
        seen.add(lid)
        report.loaded += 1

    return lessons, report


def context_sources(mapping):
    return mapping.get("context_sources") or {}


def load_context_sources(mapping, fetch=None):
    """All context source items, any number of sources. fetch(table) -> rows replaces the files (e.g. SPARQL)."""
    items = []
    for source, m in context_sources(mapping).items():
        if fetch:
            rows = fetch(source)
        else:
            rows = read_rows(m["file"], m.get("delimiter"), m.get("sheet"), m.get("header_row", 1), m.get("encoding"))
        for row in rows:
            attrs = {k: (v or "").strip() for k, v in row.items()}
            item_id = attrs.get(m["id"], "")
            if not item_id:
                continue
            text = "\n".join(attrs.get(c, "") for c in m.get("text", [])).strip()
            items.append(ContextItem(source=source, id=item_id, name=attrs.get(m.get("name", m["id"]), item_id),
                                     attrs=attrs, text=text))
    return items


def load_all(mapping, fetch=None):
    lessons, report = load_lessons(mapping, rows=fetch("lessons") if fetch else None)
    items = load_context_sources(mapping, fetch)
    for source, m in context_sources(mapping).items():
        if not m.get("lesson_column"):
            continue  # reference-only source
        known = {i.key(m.get("match_on", "name")) for i in items if i.source == source}
        for lesson in lessons:
            for value in lesson.context.get(m["lesson_column"], []):
                if value not in known:
                    report.unknown_links.setdefault(source, set()).add(value)
    return lessons, items, report

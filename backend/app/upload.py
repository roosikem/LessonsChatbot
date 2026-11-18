"""Profile an uploaded lessons file and turn the admin's column choices into a mapping."""
import copy
import re
from collections import Counter

from app.dataset import context_sources, detect_csv, load_context_sources, read_rows

ROLES = ["id", "title", "text", "context", "ranking", "filter", "ignore"]
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
SEPARATORS = [";", "|", "\n"]


def profile(path, sheet=None, header_row=1, sample=5):
    csv_options = {}
    if str(path).lower().endswith(".csv"):
        encoding, delimiter = detect_csv(path)
        csv_options = {"encoding": encoding, "delimiter": delimiter}
    rows = read_rows(path, csv_options.get("delimiter"), sheet, header_row, csv_options.get("encoding"))
    columns = list(rows[0].keys()) if rows else []
    stats = []
    for col in columns:
        values = [(r.get(col) or "").strip() for r in rows]
        filled = [v for v in values if v]
        distinct = Counter(filled)
        sep = next((s for s in SEPARATORS if sum(s in v for v in filled) >= max(2, len(filled) // 20)), None)
        stats.append({
            "column": col,
            "filled": len(filled),
            "empty": len(values) - len(filled),
            "distinct": len(distinct),
            "avg_length": round(sum(map(len, filled)) / len(filled), 1) if filled else 0,
            "numeric": bool(filled) and all(is_number(v) for v in filled),
            "max": max((float(v) for v in filled), default=None) if filled and all(is_number(v) for v in filled) else None,
            "date": bool(filled) and all(DATE.match(v) for v in filled),
            "separator": sep,
            "top": distinct.most_common(5),
            # all values when there are few, so the admin can pick filters from the full list
            "values": sorted(distinct) if len(distinct) <= 50 else None,
        })
    return {"rows": len(rows), "columns": stats, "sample": rows[:sample], "csv": csv_options}


def is_number(value):
    try:
        float(value)
        return True
    except ValueError:
        return False


def suggest(profile_result, current_mapping=None, personal_hints=()):
    """Guess a role per column. Known column names keep their role from the current mapping."""
    known = known_roles(current_mapping or {})
    known_seps = (current_mapping or {}).get("lessons", {}).get("multi_value", {})
    source_keys = keys_by_source(current_mapping or {})
    rows = profile_result["rows"] or 1
    suggestion = []
    for c in profile_result["columns"]:
        col = c["column"]
        if col in known:
            role, dim = known[col]
        elif any(hint.lower() in col.lower() for hint in personal_hints):
            role, dim = "ignore", None  # personal data stays out unless the admin says otherwise
        elif c["distinct"] == c["filled"] == rows and c["avg_length"] < 20:
            role, dim = "id", None
        elif c["date"] or (c["numeric"] and c["distinct"] <= 20):
            # small numeric scales (ratings, scores) and dates become ranking signals, weight 0 until set
            role, dim = "ranking", dimension_name(col)
        elif c["avg_length"] > 80:
            role, dim = "text", None
        elif (source := linked_source(c, source_keys)):
            # values name items of a context source: use that source's lesson column, so the link works
            role, dim = "context", context_sources(current_mapping)[source]["lesson_column"]
        elif c["filled"] and c["distinct"] <= max(20, c["filled"] * 0.5):
            role, dim = "context", dimension_name(col)
        else:
            role, dim = "ignore", None
        suggestion.append({"column": col, "role": role, "dimension": dim,
                           "separator": known_seps.get(col, c["separator"]),
                           "known": col in known})
    return suggestion


def keys_by_source(mapping):
    """{source: set of item keys (names or ids, as the lessons refer to them)}"""
    try:
        items = load_context_sources(mapping)
    except (OSError, KeyError):
        return {}
    out = {}
    for source, cfg in context_sources(mapping).items():
        if cfg.get("lesson_column"):
            out[source] = {i.key(cfg.get("match_on", "name")).casefold() for i in items if i.source == source}
    return out


def linked_source(stats, source_keys):
    """The context source whose items this column names (at least half of its values), or None."""
    if not source_keys or not stats["values"]:
        return None
    values = [part.strip().casefold() for v in stats["values"]
              for part in v.split(stats["separator"] or "\0") if part.strip()]
    best, share = None, 0.5
    for source, keys in source_keys.items():
        hit = sum(v in keys for v in values) / len(values) if values else 0
        if hit >= share:
            best, share = source, hit
    return best


def known_roles(mapping):
    m = mapping.get("lessons", {})
    out = {m.get("id"): ("id", None), m.get("title"): ("title", None)}
    out.update({c: ("text", None) for c in m.get("text", [])})
    out.update({col: ("context", dim) for dim, col in m.get("context", {}).items()})
    for name, spec in (m.get("ranking") or {}).items():
        out[spec if isinstance(spec, str) else spec["column"]] = ("ranking", name)
    out.update({col: ("filter", None) for col in m.get("filter", {})})
    out.update({col: ("ignore", None) for col in m.get("ignore", [])})
    out.pop(None, None)
    return out


def dimension_name(column):
    return re.sub(r"[^a-z0-9]+", "_", column.lower()).strip("_") or "dimension"


def build_mapping(base, file_path, roles, filters=None, sheet=None, header_row=1, csv_options=None, profile_result=None):
    """roles: [{column, role, dimension?, separator?}] -> a full mapping (context sources kept from base).
    For ranking columns, `dimension` is the signal name; known signals keep their kind / scale / weight."""
    errors = []
    by_role = {}
    for r in roles:
        if r["role"] not in ROLES:
            errors.append(f"unknown role {r['role']} for {r['column']}")
        by_role.setdefault(r["role"], []).append(r)
    for needed in ("id", "text"):
        if not by_role.get(needed):
            errors.append(f"pick a column for '{needed}'")
    for single in ("id", "title"):
        if len(by_role.get(single, [])) > 1:
            errors.append(f"only one column can be '{single}'")
    names = [r["dimension"] or dimension_name(r["column"]) for r in by_role.get("ranking", [])]
    if len(names) != len(set(names)):
        errors.append("two ranking columns have the same name")
    dims = [r["dimension"] or dimension_name(r["column"]) for r in by_role.get("context", [])]
    if len(dims) != len(set(dims)):
        errors.append("two context columns have the same dimension name")
    if errors:
        raise ValueError("; ".join(errors))

    lessons = {
        "file": str(file_path),
        "id": by_role["id"][0]["column"],
        "title": by_role["title"][0]["column"] if by_role.get("title") else None,
        "text": [r["column"] for r in by_role["text"]],
        "context": {(r["dimension"] or dimension_name(r["column"])): r["column"] for r in by_role.get("context", [])},
        "ranking": ranking_config(by_role.get("ranking", []), base, profile_result),
        "filter": {r["column"]: (filters or {}).get(r["column"], []) for r in by_role.get("filter", [])},
        "multi_value": {r["column"]: r["separator"] for r in roles if r.get("separator") and r["role"] == "context"},
        "ignore": [r["column"] for r in by_role.get("ignore", [])],
    }
    lessons.update(csv_options or {})
    if sheet:
        lessons["sheet"] = sheet
    if header_row != 1:
        lessons["header_row"] = header_row
    lessons["filter"] = {k: v for k, v in lessons["filter"].items() if v}
    if not lessons["title"]:
        del lessons["title"]  # titles will be taken from the text

    mapping = copy.deepcopy(base)
    mapping["lessons"] = lessons
    return mapping


def ranking_config(rows, base, profile_result=None):
    """Signal settings for the ranking columns: known signals keep theirs, new ones get kind/max from the
    profile and weight 0, so they're stored but don't change the ranking until someone sets a weight."""
    known = {}
    for name, spec in ((base.get("lessons") or {}).get("ranking") or {}).items():
        spec = {"column": spec} if isinstance(spec, str) else spec
        known[spec["column"]] = (name, spec)
    stats = {c["column"]: c for c in (profile_result or {}).get("columns", [])}
    out = {}
    for r in rows:
        if r["column"] in known:
            name, spec = known[r["column"]]
            out[r["dimension"] or name] = dict(spec)
            continue
        c = stats.get(r["column"], {})
        if c.get("date"):
            spec = {"column": r["column"], "kind": "date", "half_life_days": 1095, "weight": 0}
        else:
            spec = {"column": r["column"], "kind": "number", "max": c.get("max") or 1, "weight": 0}
        out[r["dimension"] or dimension_name(r["column"])] = spec
    return out

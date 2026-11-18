"""Ranking signals from the lesson data (impact, ratings, recency...), declared in the mapping:

  ranking:
    impact:  {column: "Impact (0-5)", kind: number, max: 5, weight: 0.05}
    recency: {column: Created, kind: date, half_life_days: 1095, weight: 0.02}

Any number of signals; a weight of 0 keeps the value for display without changing the ranking.
"""
from datetime import date


def config(mapping):
    """Signal settings from the mapping. A plain column name is accepted as a number signal."""
    out = {}
    for name, spec in ((mapping.get("lessons") or {}).get("ranking") or {}).items():
        spec = {"column": spec} if isinstance(spec, str) else dict(spec)
        spec.setdefault("kind", "number")
        spec.setdefault("weight", 0.0)
        out[name] = spec
    return out


def read(row, signals):
    """Raw values of one lesson row: numbers as float, dates as ISO text, missing as None."""
    out = {}
    for name, spec in signals.items():
        raw = (row.get(spec["column"]) or "").strip()
        if spec["kind"] == "date":
            out[name] = raw[:10] or None
        else:
            try:
                out[name] = float(raw)
            except ValueError:
                out[name] = None
    return out


def normalized(name, value, spec, today=None):
    if value is None:
        return 0.0
    if spec["kind"] == "date":
        try:
            age = ((today or date.today()) - date.fromisoformat(value)).days
        except ValueError:
            return 0.0
        return 0.5 ** (max(age, 0) / spec.get("half_life_days", 365))
    top = spec.get("max") or 1
    return min(max(value / top, 0.0), 1.0)


def score(values, signals, today=None):
    """Weighted sum of the normalized signals, 0 when nothing is configured."""
    return sum(spec["weight"] * normalized(name, values.get(name), spec, today) for name, spec in signals.items())

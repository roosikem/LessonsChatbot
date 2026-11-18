import difflib
import re


def normalize(context):
    """Turn whatever the model or a client sent into {dimension: [values]}; drop the rest."""
    if not isinstance(context, dict):
        return {}
    out = {}
    for dim, values in context.items():
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, (list, tuple)):
            continue
        cleaned = [str(v).strip() for v in values if str(v).strip()]
        if cleaned:
            out[str(dim)] = cleaned
    return out


def matches(lesson_context, wanted):
    """(dimension, value) pairs from `wanted` that the lesson really has. Case-insensitive, exact values."""
    found = []
    for dim, values in normalize(wanted).items():
        have = {v.casefold() for v in lesson_context.get(dim, [])}
        found += [(dim, v) for v in values if v.casefold() in have]
    return found


def match_score(term, value):
    """How well a user's word matches a value in the data, 0..1.
    exact 1.0 · whole word / word start (4+ letters) 0.85 · typo (same first 3 letters) its similarity."""
    t, v = term.casefold().strip(), value.casefold().strip()
    if not t or not v:
        return 0.0
    if t == v:
        return 1.0
    words = re.findall(r"\w+", v)
    t_words = re.findall(r"\w+", t)
    if len(t) >= 4 and (all(any(w.startswith(tw) for w in words) for tw in t_words)):
        return 0.85
    if t[:3] == v[:3]:
        ratio = difflib.SequenceMatcher(None, t, v).ratio()
        if ratio >= 0.85:
            return round(ratio, 2)
    return 0.0


def resolve(term, dimensions, dimension=None, limit=5):
    """Map a user's word to known context values, e.g. 'comissioning' -> stage=Commissioning."""
    found = []
    for dim, values in dimensions.items():
        if dimension and dim != dimension:
            continue
        for v in values:
            score = match_score(term, v)
            if score:
                found.append({"dimension": dim, "value": v, "score": score})
    found.sort(key=lambda x: x["score"], reverse=True)
    return {"term": term, "matches": found[:limit]}


def align(context, dimensions):
    """Map loose context values to the data's own values, e.g. {"stage": ["comissioning"]} ->
    {"stage": ["Commissioning"]}. Returns (context, changes, unresolved). A value is only moved to
    another dimension when that's the one clear match; anything ambiguous is left for the model."""
    out, changes, unresolved = {}, [], []
    for dim, values in normalize(context).items():
        known = dimensions.get(dim)
        for value in values:
            target = (dim, value)
            matches = resolve(value, dimensions, dim if known is not None else None)["matches"]
            exact = [m for m in matches if m["score"] == 1.0]
            clear = exact[:1] if len(exact) == 1 else (
                matches[:1] if len(matches) == 1 or (matches and not exact and matches[0]["score"] > matches[1]["score"])
                else [])
            if known is not None and clear:
                target = (dim, clear[0]["value"])
            elif known is not None and matches:
                # e.g. project "line" fits Line 4 and Line 5 equally: let the model ask or choose
                unresolved.append({"term": value, "dimension": dim,
                                   "candidates": [f"{m['dimension']}={m['value']}" for m in matches]})
            elif known is None and (len(exact) == 1 or len(matches) == 1):
                best = exact[0] if exact else matches[0]
                target = (best["dimension"], best["value"])
            elif known is None and matches:
                unresolved.append({"term": value, "dimension": dim,
                                   "candidates": [f"{m['dimension']}={m['value']}" for m in matches]})
            if target != (dim, value):
                changes.append(f"{dim}={value} -> {target[0]}={target[1]}")
            out.setdefault(target[0], [])
            if target[1] not in out[target[0]]:
                out[target[0]].append(target[1])
    return out, changes, unresolved

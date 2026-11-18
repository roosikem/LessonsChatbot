"""Context sources: extra tables linked to the lessons (projects, suppliers, components...).

Any number of them, each described in the mapping under `context_sources`. A lesson
points to items through one of its context columns (`lesson_column`). A source without
`lesson_column` is reference-only: other sources point to it through `references`.
"Comparable" uses the weighted `compare` attributes; without them a source is a plain list.
"""
NEGATIVE = {"false", "no", "0", "n"}


class Sources:
    """The items of every context source, plus how lessons link to them."""

    def __init__(self, items, mapping):
        self.config = mapping.get("context_sources") or {}
        self.items = {name: [i for i in items if i.source == name] for name in self.config}
        self.by_key = {name: {i.key(cfg.get("match_on", "name")): i for i in self.items[name]}
                       for name, cfg in self.config.items()}

    def names(self):
        return list(self.config)

    def lesson_column(self, source):
        return self.config[source].get("lesson_column")

    def weights(self, source):
        return self.config[source].get("compare") or {}

    def find(self, source, name_or_id):
        """Exact id or name; otherwise a part of a name, but only if it fits one item ("Line 5", not "Valoria")."""
        items = self.items.get(source, [])
        needle = str(name_or_id).strip().lower()
        for item in items:
            if needle in (item.id.lower(), item.name.lower()):
                return item
        partial = self.candidates(source, name_or_id)
        return partial[0] if len(partial) == 1 else None

    def candidates(self, source, name_or_id):
        needle = str(name_or_id).strip().lower()
        return [i for i in self.items.get(source, []) if needle and needle in i.name.lower()]

    def resolve(self, related_to):
        """{source: name or id} from a caller -> {source: item}; unknown sources / items are left out."""
        out = {}
        for source, value in (related_to or {}).items():
            if source in self.config and value:
                item = self.find(source, value)
                if item:
                    out[source] = item
        return out

    def not_found(self, related_to, targets):
        """Named items that weren't resolved: {source: candidate names}; empty list = no item fits at all."""
        return {source: [i.name for i in self.candidates(source, value)][:20]
                for source, value in (related_to or {}).items() if source not in targets}

    def linked_items(self, lesson_context, source):
        column = self.lesson_column(source)
        if not column:
            return []
        return [self.by_key[source][v] for v in lesson_context.get(column, []) if v in self.by_key[source]]

    def boost(self, lesson_context, targets):
        """How close a lesson is to the target items (0..1, averaged over targets) and the reasons."""
        if not targets:
            return 0.0, []
        total, reasons = 0.0, []
        for source, target in targets.items():
            best, reason = 0.0, None
            for item in self.linked_items(lesson_context, source):
                if item.id == target.id:
                    best, reason = 1.0, ("same_item", source, item.name)
                    break
                score, matched = similarity(target, item, self.weights(source))
                if score > best:
                    best, reason = score, ("comparable_item", source, item.name, matched)
            total += best
            if reason:
                reasons.append(reason)
        return total / len(targets), reasons

    def comparable(self, source, target, limit=5):
        scored = []
        for item in self.items.get(source, []):
            if item.id == target.id:
                continue
            score, matched = similarity(target, item, self.weights(source))
            if score > 0:
                scored.append((item, score, matched))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def describe(self):
        """Short description for prompts: which sources exist and how lessons link to them."""
        return {name: {"lesson_column": cfg.get("lesson_column"), "items": len(self.items[name]),
                       "compare": list(self.weights(name)), "references": cfg.get("references") or {}}
                for name, cfg in self.config.items()}


def similarity(a, b, weights):
    """Share of weighted attributes two items have in common, 0..1, plus the matches."""
    total, score, matches = 0.0, 0.0, []
    for attr, w in weights.items():
        va, vb = a.attrs.get(attr, "").lower(), b.attrs.get(attr, "").lower()
        # missing values say nothing, and two items both lacking a feature isn't a real match
        if not va or not vb or (va in NEGATIVE and vb in NEGATIVE):
            continue
        total += w
        if va == vb:
            score += w
            matches.append((attr, a.attrs[attr]))
    return (score / total if total else 0.0), matches


def comparable_result(sources, source, name, limit=5):
    """The comparable_items answer, shared by the memory and graph agents so both reply the same way."""
    if source not in sources.names():
        return {"error": f"unknown context source {source}", "sources": sources.names()}
    target = sources.find(source, name)
    if target is None:
        close = [i.name for i in sources.candidates(source, name)]
        if len(close) > 1:
            return {"error": f"{name} fits several {source} items; ask which one", "candidates": close[:20]}
        return {"error": f"no {source} called {name}", "known": [i.name for i in sources.items[source]][:50]}
    return {
        "source": source,
        "item": target.name,
        "attributes": {a: target.attrs.get(a) for a in sources.weights(source)},
        "comparable": [{"name": i.name, "score": round(s, 2), "shared": dict(m)}
                       for i, s, m in sources.comparable(source, target, limit)],
    }

"""Evidence grader: does each retrieved lesson really help with the question?

Separate from the answer agent so it can use a smaller model, run as its own
service, or be switched off (FEATURE_EVIDENCE_GRADING).
"""
GRADES = ("relevant", "partial", "not")

SYSTEM = """You check search results before an answer is written. For each lesson, decide whether it helps the user with their situation.

- relevant: it addresses the user's problem, component, project type or phase directly. The context line (stage, topic, supplier, project...) counts as much as the text.
- partial: related experience that could still help, but not the user's actual problem.
- not: a different topic. Sharing a generic word with the question is not enough.

Be strict. If the user asks about something none of the lessons cover, grade them "not". Give only the grades, no explanations.
missing: what the user asked that none of the lessons cover (empty if covered).
next_step: if nothing is relevant, one short suggestion for the user (e.g. other wording, a related topic that does exist, or whom to ask). Empty otherwise.
Write missing and next_step in the user's language."""

SCHEMA = {
    "type": "object",
    "properties": {
        "grades": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "grade": {"type": "string", "enum": list(GRADES)},
            },
            "required": ["id", "grade"],
        }},
        "missing": {"type": "string"},
        "next_step": {"type": "string"},
    },
    "required": ["grades", "missing", "next_step"],
}


class GraderAgent:
    name = "grader"
    methods = ("info", "grade")

    def __init__(self, settings, llm=None):
        from app.llm import make_llm
        self.model = settings.grader_model_id or settings.llm_model_id
        # temperature 0: the same candidates should get the same grades
        self.llm = llm or make_llm(settings, provider=settings.grader_provider, model_id=self.model, temperature=0)
        self.text_chars = 600

    def info(self):
        return {"model": self.model}

    def grade(self, question, candidates):
        """candidates: [{id, title, text, context?}] -> {grades: {id: grade}, valid, usage, missing, next_step}.
        `valid` counts the grades the model really gave; the rest default to "partial"."""
        if not candidates:
            return {"grades": {}, "valid": 0, "usage": {}, "missing": "", "next_step": ""}
        listing = "\n\n".join(describe(c, self.text_chars) for c in candidates)
        prompt = f"Question: {question}\n\nLessons found:\n\n{listing}"
        reply = self.llm.chat(SYSTEM, [{"role": "user", "content": prompt}], schema=SCHEMA)
        data = reply.data or {}

        ids = {c["id"] for c in candidates}
        grades = {}
        for g in data.get("grades", []):
            lid = str(g.get("id", "")).strip().strip("[]")
            if lid in ids and g.get("grade") in GRADES:
                grades[lid] = g["grade"]
        valid = len(grades)
        for lid in ids - grades.keys():
            grades[lid] = "partial"  # the model skipped it: keep it, but don't trust it fully
        return {"grades": grades, "valid": valid, "usage": reply.usage,
                "missing": (data.get("missing") or "").strip(), "next_step": (data.get("next_step") or "").strip()}


def describe(candidate, text_chars):
    context = "; ".join(f"{dim}: {', '.join(values)}" for dim, values in (candidate.get("context") or {}).items() if values)
    lines = [f"[{candidate['id']}] {candidate['title']}"]
    if context:
        lines.append(f"Context: {context}")
    lines.append((candidate.get("text") or "")[:text_chars])
    return "\n".join(lines)

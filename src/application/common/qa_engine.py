"""Canonical adapter from profile reasoning to platform form engines."""

from .profile_reasoner import ProfileReasoner


def _diag_result(result):
    if not isinstance(result, dict):
        return result
    return {
        "answer": result.get("answer"),
        "field": result.get("field"),
        "kind": result.get("kind"),
        "confidence": result.get("confidence"),
    }


class AnswerEngine:
    def __init__(self, reasoner=None):
        self.reasoner = reasoner or ProfileReasoner()

    def evidence(self, question, limit=14):
        """Return deterministic evidence without issuing a model request."""
        print(f"  DIAG AnswerEngine.evidence question={question!r}")
        print(
            "  DIAG AnswerEngine.evidence reasoner="
            f"{self.reasoner.__class__.__module__}.{self.reasoner.__class__.__name__}"
        )
        try:
            result = self.reasoner._local_reason(question, [])
        except Exception as exc:
            print(f"  DIAG AnswerEngine.evidence exception={type(exc).__name__}: {exc}")
            result = None
        if result:
            if result.get("field"):
                evidence = f"deterministic profile field: {result['field']}"
                print(f"  DIAG AnswerEngine.evidence result={_diag_result(result)!r} returned={evidence!r}")
                return evidence
            if result.get("answer") is not None:
                evidence = "deterministic profile evidence available"
                print(f"  DIAG AnswerEngine.evidence result={_diag_result(result)!r} returned={evidence!r}")
                return evidence
        evidence = "no deterministic profile evidence"
        print(f"  DIAG AnswerEngine.evidence result={_diag_result(result)!r} returned={evidence!r}")
        return evidence

    def answer(self, question, options=None):
        result = self.reasoner.reason(question, options or [])
        print(f"  DIAG AnswerEngine.answer question={question!r} result={_diag_result(result)!r}")
        if not result:
            return None, None, None
        return result.get("answer"), result.get("field"), result.get("kind")

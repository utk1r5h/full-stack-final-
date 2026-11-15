"""Explainable lost/found comparison engine.

Scores are deterministic similarity rankings, NOT probabilities. Every
opposite-type report receives a score for authorised staff visibility.
Recommendation eligibility remains a separate flag using the original
category, identity-evidence and minimum-score rules.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from difflib import SequenceMatcher

from .models import Claim, Item


WEIGHTS = {
    "name": 22,
    "category": 12,
    "description": 20,
    "features": 16,
    "colour": 8,
    "location": 10,
    "date": 12,
}
MIN_MATCH_SCORE = 42

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "the", "to", "with", "item", "lost",
    "found", "my", "this", "that", "was", "were", "near", "around",
}
COLOUR_GROUPS = {
    "black": {"black", "jet black", "midnight", "onyx"},
    "white": {"white", "ivory", "cream", "pearl"},
    "blue": {"blue", "navy", "royal blue", "sky blue", "navy blue"},
    "red": {"red", "maroon", "burgundy", "crimson"},
    "green": {"green", "olive", "mint", "emerald"},
    "grey": {"grey", "gray", "silver", "space grey", "space gray"},
    "brown": {"brown", "tan", "beige", "coffee"},
    "pink": {"pink", "rose", "magenta"},
    "purple": {"purple", "violet", "lavender"},
    "yellow": {"yellow", "gold", "golden"},
}


def normalize(value: str | None) -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens(value: str | None) -> list[str]:
    return [token for token in normalize(value).split() if token and token not in STOP_WORDS]


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _char_ngrams(value: str, n: int = 3) -> Counter:
    compact = normalize(value).replace(" ", "")
    if not compact:
        return Counter()
    if len(compact) < n:
        return Counter([compact])
    return Counter(compact[i:i + n] for i in range(len(compact) - n + 1))


def _cosine(left: Counter, right: Counter) -> float:
    if not left or not right:
        return 0.0
    dot = sum(count * right.get(term, 0) for term, count in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _tfidf_cosine(left_text: str | None, right_text: str | None) -> float:
    """Two-document TF-IDF cosine similarity using word unigrams/bigrams."""
    left_tokens, right_tokens = tokens(left_text), tokens(right_text)
    if not left_tokens or not right_tokens:
        return 0.0

    def terms(words: list[str]) -> Counter:
        result = Counter(words)
        result.update(f"{words[i]}_{words[i + 1]}" for i in range(len(words) - 1))
        return result

    left_tf, right_tf = terms(left_tokens), terms(right_tokens)
    vocabulary = set(left_tf) | set(right_tf)
    vectors = []
    for document in (left_tf, right_tf):
        vector = {}
        for term in vocabulary:
            document_frequency = int(term in left_tf) + int(term in right_tf)
            idf = math.log(1 + 2 / (1 + document_frequency)) + 1
            vector[term] = (1 + math.log(document[term])) * idf if document.get(term) else 0.0
        vectors.append(Counter({key: value for key, value in vector.items() if value}))
    return _cosine(vectors[0], vectors[1])


def text_similarity(left: str | None, right: str | None, *, field: str = "description") -> float | None:
    """Return a 0..1 hybrid score; None means there is no comparable evidence."""
    if not (normalize(left) and normalize(right)):
        return None
    left_tokens, right_tokens = set(tokens(left)), set(tokens(right))
    jaccard = _jaccard(left_tokens, right_tokens)
    char_cosine = _cosine(_char_ngrams(left), _char_ngrams(right))
    sequence = SequenceMatcher(None, normalize(left), normalize(right)).ratio()
    word_tfidf = _tfidf_cosine(left, right)

    if field == "name":
        score = 0.35 * jaccard + 0.25 * char_cosine + 0.25 * sequence + 0.15 * word_tfidf
    elif field == "location":
        score = 0.45 * jaccard + 0.30 * char_cosine + 0.25 * sequence
    else:
        score = 0.45 * word_tfidf + 0.30 * jaccard + 0.15 * char_cosine + 0.10 * sequence
    return max(0.0, min(1.0, score))


def colour_similarity(left: str | None, right: str | None) -> tuple[float | None, bool]:
    """Return similarity and a clear-conflict flag for colour descriptions."""
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return None, False
    if a == b:
        return 1.0, False
    group_a = next((key for key, values in COLOUR_GROUPS.items() if a in values), None)
    group_b = next((key for key, values in COLOUR_GROUPS.items() if b in values), None)
    if group_a and group_a == group_b:
        return 0.9, False
    similarity = text_similarity(a, b, field="location") or 0.0
    return similarity, similarity < 0.25


def date_similarity(left, right) -> float:
    """Exponential time decay: same day=1, then similarity falls smoothly."""
    days = abs((left - right).days)
    return math.exp(-days / 14.0)


def category_compatible(left: str, right: str) -> tuple[bool, float]:
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return False, 0.0
    if a == b:
        return True, 1.0
    similarity = text_similarity(a, b, field="name") or 0.0
    # Categories are an important gate: broad category overlap alone is not enough.
    return similarity >= 0.72, similarity


def _active_claim_exists(item: Item) -> bool:
    return Claim.objects.filter(
        item=item,
        status__in=[Claim.Status.APPROVED, Claim.Status.RETURNED],
    ).exists()


def score_pair(source: Item, candidate: Item) -> dict:
    """Score a LOST/FOUND pair, even when it is a weak/non-recommended match."""
    compatible, category_score = category_compatible(source.category, candidate.category)

    name_score = text_similarity(source.name, candidate.name, field="name") or 0.0
    description_score = text_similarity(source.description, candidate.description, field="description") or 0.0
    feature_score = text_similarity(source.identifying_features, candidate.identifying_features, field="description")
    colour_score, colour_conflict = colour_similarity(source.colour, candidate.colour)
    location_score = text_similarity(source.location, candidate.location, field="location")
    days_apart = abs((source.date_lost_found - candidate.date_lost_found).days)
    time_score = date_similarity(source.date_lost_found, candidate.date_lost_found)

    component_scores = {
        "name": name_score,
        "category": category_score,
        "description": description_score,
        "features": feature_score,
        "colour": colour_score,
        "location": location_score,
        "date": time_score,
    }
    raw_score = sum(WEIGHTS[key] * value for key, value in component_scores.items() if value is not None)
    available_weight = sum(WEIGHTS[key] for key, value in component_scores.items() if value is not None)
    coverage = available_weight / sum(WEIGHTS.values())

    penalties = 0
    warnings = []
    if colour_conflict:
        penalties += 7
        warnings.append("The reported colours conflict.")
    if location_score is not None and location_score < 0.18:
        penalties += 6
        warnings.append("The reported locations are different.")
    if days_apart > 30:
        penalties += 8
        warnings.append("The report dates are more than 30 days apart.")
    if name_score < 0.12 and description_score < 0.12 and (feature_score or 0) < 0.12:
        penalties += 18
        warnings.append("There is almost no overlap in the item identity or description.")

    score = max(0, min(100, round(raw_score - penalties)))

    # Preserve the original recommendation gates, but do not discard the
    # comparison. Staff can inspect every score and its reasons/warnings.
    identity_evidence = max(name_score, description_score, feature_score or 0.0)
    recommendation_eligible = (
        compatible
        and identity_evidence >= 0.16
        and score >= MIN_MATCH_SCORE
    )
    if not compatible:
        warnings.append("Category compatibility is low; review this comparison carefully.")
    if identity_evidence < 0.16:
        warnings.append("Very little item-name, description or identifying-feature evidence.")
    if score < MIN_MATCH_SCORE:
        warnings.append(f"Below the original {MIN_MATCH_SCORE}/100 recommendation threshold.")

    reasons = []
    for key, label in (
        ("name", "Item-name similarity"),
        ("description", "Description similarity"),
        ("features", "Identifying-feature similarity"),
        ("category", "Category compatibility"),
        ("colour", "Colour agreement"),
        ("location", "Location similarity"),
        ("date", "Date proximity"),
    ):
        value = component_scores[key]
        if value is not None and value >= 0.55:
            reasons.append(label)

    if score >= 78:
        confidence = "Strong candidate"
    elif score >= 60:
        confidence = "Promising candidate"
    elif recommendation_eligible:
        confidence = "Possible candidate"
    else:
        confidence = "Low similarity"
    if coverage < 0.70:
        warnings.append("Some comparison details are missing; treat this score cautiously.")

    breakdown = {
        key: "N/A" if value is None else round(value * 100)
        for key, value in component_scores.items()
    }
    breakdown["penalties"] = penalties
    breakdown["days_apart"] = days_apart

    return {
        "item": candidate,
        "score": score,
        "confidence": confidence,
        "recommendation_eligible": recommendation_eligible,
        "category_compatible": compatible,
        "identity_evidence": round(identity_evidence * 100),
        "coverage": round(coverage * 100),
        "breakdown": breakdown,
        "reasons": reasons,
        "warnings": warnings,
    }


def possible_matches(item: Item, limit: int | None = None) -> list[dict]:
    """Score every opposite-type report for authorised staff visibility.

    No status, claim-state, category, identity-evidence or 42-point filter is
    used to hide a comparison. The original recommendation rules are exposed
    as ``recommendation_eligible`` on each result. Optional ``limit`` is kept
    for compatibility, but item-detail views request the complete list.
    """
    opposite = (
        Item.ReportType.FOUND
        if item.report_type == Item.ReportType.LOST
        else Item.ReportType.LOST
    )
    candidates = (
        Item.objects.filter(report_type=opposite)
        .exclude(pk=item.pk)
        .select_related("reported_by")
    )

    results = [score_pair(item, candidate) for candidate in candidates.iterator()]
    results.sort(
        key=lambda result: (result["score"], result["coverage"]),
        reverse=True,
    )
    return results if limit is None else results[:limit]

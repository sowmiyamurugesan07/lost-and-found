"""Smart matching for Lost & Found+.

Pure-Python TF-IDF + cosine similarity and a weighted, explainable scoring
model. This module has no database or Flask imports so it can be unit-tested
on its own.

Scoring model
-------------
Each factor produces a value between 0.0 and 1.0. A factor is only counted
when BOTH reports contain usable information for it, so missing data can
never create a match. The weights of the counted factors are re-normalised
to 1.0 and the final score is `sum(value * weight) * 100`.

Conflicts (for example a black wallet vs a pink wallet, or a found date
before the lost date) subtract a small penalty and are shown to the user.

Thresholds come from config (`MATCH_THRESHOLDS`) but sane defaults are used
when this module is imported outside Flask.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from difflib import SequenceMatcher

# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

STOPWORDS = {
    'a', 'an', 'the', 'and', 'or', 'but', 'of', 'in', 'on', 'at', 'to', 'for',
    'with', 'by', 'from', 'near', 'inside', 'outside', 'is', 'was', 'were',
    'it', 'its', 'this', 'that', 'these', 'those', 'my', 'mine', 'i', 'me',
    'has', 'have', 'had', 'be', 'been', 'as', 'some', 'any', 'very', 'also',
    'found', 'lost', 'item', 'please', 'about', 'around', 'containing',
    'contains', 'small', 'big', 'top', 'bottom',
}

SYNONYMS = {
    'mobile': 'phone', 'cellphone': 'phone', 'smartphone': 'phone',
    'earphone': 'headphone', 'earphones': 'headphone', 'headphones': 'headphone',
    'earbuds': 'headphone', 'earbud': 'headphone',
    'wallet': 'wallet', 'purse': 'wallet',
    'bag': 'bag', 'backpack': 'bag', 'rucksack': 'bag', 'schoolbag': 'bag',
    'skybag': 'bag', 'slick': 'bag',
    'bottle': 'bottle', 'flask': 'bottle', 'waterbottle': 'bottle',
    'laptop': 'laptop', 'notebook': 'laptop', 'macbook': 'laptop',
    'id': 'idcard', 'idcard': 'idcard', 'identity': 'idcard',
    'spectacles': 'glasses', 'specs': 'glasses', 'eyeglasses': 'glasses',
    'umbrella': 'umbrella', 'watch': 'watch', 'wristwatch': 'watch',
    'charger': 'charger', 'adapter': 'charger',
    'book': 'book', 'notebooks': 'book', 'textbook': 'book',
    'key': 'keys', 'keys': 'keys', 'keychain': 'keys',
}


def normalize_text(value) -> str:
    """Lowercase, strip punctuation and collapse whitespace."""
    if value is None:
        return ''
    text = str(value).lower().strip()
    text = re.sub(r'[\u2018\u2019\u201c\u201d]', "'", text)
    text = re.sub(r'[^a-z0-9\s\']', ' ', text)
    text = text.replace("'", '')
    return re.sub(r'\s+', ' ', text).strip()


def tokenize(value, keep_stopwords: bool = False) -> list[str]:
    """Normalise text into meaningful tokens with a light plural stem."""
    text = normalize_text(value)
    if not text:
        return []
    words = []
    for word in text.split():
        if not keep_stopwords and word in STOPWORDS:
            continue
        if len(word) > 3 and word.endswith('ies'):
            word = word[:-3] + 'y'
        elif len(word) > 3 and word.endswith('es') and not word.endswith('ses'):
            word = word[:-2]
        elif len(word) > 3 and word.endswith('s') and not word.endswith('ss'):
            word = word[:-1]
        word = SYNONYMS.get(word, word)
        words.append(word)
    return words


def _token_set(value) -> set[str]:
    return set(tokenize(value))


def token_overlap(a, b) -> float:
    """Symmetric token similarity (Jaccard) in [0, 1]."""
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def text_similarity(a, b) -> float:
    """Blend token overlap and character sequence similarity."""
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    overlap = token_overlap(na, nb)
    ratio = SequenceMatcher(None, na, nb).ratio()
    score = 0.6 * overlap + 0.4 * ratio
    # One value fully contained in the other (e.g. "wallet" vs "black wallet")
    if na in nb or nb in na:
        score = max(score, 0.85)
    return min(1.0, score)


# ---------------------------------------------------------------------------
# TF-IDF cosine similarity
# ---------------------------------------------------------------------------

def _term_frequencies(tokens: list[str]) -> dict[str, float]:
    counts: dict[str, float] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0.0) + 1.0
    total = float(len(tokens)) or 1.0
    return {term: count / total for term, count in counts.items()}


def tfidf_cosine(text_a, text_b) -> float:
    """Cosine similarity of TF-IDF vectors built from the two documents."""
    tokens_a = tokenize(text_a)
    tokens_b = tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    tf_a = _term_frequencies(tokens_a)
    tf_b = _term_frequencies(tokens_b)
    vocabulary = set(tf_a) | set(tf_b)
    n_docs = 2
    idf = {}
    for term in vocabulary:
        df = (1 if term in tf_a else 0) + (1 if term in tf_b else 0)
        idf[term] = math.log((1 + n_docs) / (1 + df)) + 1.0
    vec_a = {t: tf_a.get(t, 0.0) * idf[t] for t in vocabulary}
    vec_b = {t: tf_b.get(t, 0.0) * idf[t] for t in vocabulary}
    dot = sum(vec_a[t] * vec_b[t] for t in vocabulary)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


# ---------------------------------------------------------------------------
# Attribute-specific similarity
# ---------------------------------------------------------------------------

COLOR_FAMILIES = {
    'black': 'dark', 'dark': 'dark', 'charcoal': 'dark',
    'white': 'light', 'cream': 'light', 'ivory': 'light', 'beige': 'light',
    'blue': 'blue', 'navy': 'blue', 'sky': 'blue', 'azure': 'blue',
    'indigo': 'blue', 'cyan': 'blue',
    'red': 'red', 'maroon': 'red', 'crimson': 'red', 'wine': 'red',
    'green': 'green', 'olive': 'green', 'teal': 'green', 'mint': 'green',
    'yellow': 'yellow', 'gold': 'yellow', 'golden': 'yellow',
    'orange': 'orange', 'peach': 'orange',
    'pink': 'pink', 'rose': 'pink', 'magenta': 'pink',
    'purple': 'purple', 'violet': 'purple', 'lavender': 'purple', 'lilac': 'purple',
    'brown': 'brown', 'tan': 'brown', 'chocolate': 'brown', 'coffee': 'brown',
    'grey': 'grey', 'gray': 'grey', 'silver': 'grey', 'ash': 'grey',
}

# Rough campus zones. Locations in the same zone are treated as nearby.
LOCATION_ZONES = {
    'library': 'academic', 'reading room': 'academic',
    'block a': 'academic', 'block b': 'academic', 'block c': 'academic',
    'block d': 'academic', 'classroom': 'academic', 'lab': 'academic',
    'laboratory': 'academic', 'computer lab': 'academic',
    'department': 'academic', 'seminar hall': 'academic',
    'canteen': 'social', 'cafeteria': 'social', 'food court': 'social',
    'auditorium': 'social', 'ground': 'social', 'sports ground': 'social',
    'playground': 'social', 'basketball court': 'social',
    'hostel': 'residential', 'hostel block': 'residential', 'mess': 'residential',
    'parking': 'transit', 'parking lot': 'transit', 'main gate': 'transit',
    'gate': 'transit', 'bus stop': 'transit', 'bus stand': 'transit',
    'admin block': 'admin', 'office': 'admin', 'reception': 'admin',
}

COLOR_LABEL = {
    'dark': 'dark/black', 'light': 'white/light', 'grey': 'grey/silver',
}


def color_similarity(color_a, color_b):
    """Return (similarity 0..1 or None, conflict bool)."""
    na, nb = normalize_text(color_a), normalize_text(color_b)
    if not na or not nb:
        return None, False
    if na == nb:
        return 1.0, False
    set_a = {COLOR_FAMILIES.get(w, w) for w in na.split()}
    set_b = {COLOR_FAMILIES.get(w, w) for w in nb.split()}
    if set_a & set_b:
        return 0.9, False
    return 0.0, True


def location_similarity(loc_a, loc_b):
    na, nb = normalize_text(loc_a), normalize_text(loc_b)
    if not na or not nb:
        return None, False
    if na == nb:
        return 1.0, False
    if na in nb or nb in na:
        return 0.95, False
    overlap = token_overlap(na, nb)
    zone_a = LOCATION_ZONES.get(na)
    zone_b = LOCATION_ZONES.get(nb)
    if zone_a and zone_b and zone_a == zone_b:
        return max(0.8, overlap), False
    return overlap, False


def _as_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def date_similarity(lost_date, found_date):
    """Compatibility of the lost date and found date.

    A found item cannot be found before it was lost. Returns
    (similarity or None, conflict bool, days_apart or None).
    """
    lost = _as_date(lost_date)
    found = _as_date(found_date)
    if lost is None or found is None:
        return None, False, None
    days = (found - lost).days
    if days < -1:
        return 0.0, True, days
    if days <= 3:
        return 1.0, False, days
    if days <= 7:
        return 0.85, False, days
    if days <= 14:
        return 0.65, False, days
    if days <= 30:
        return 0.4, False, days
    if days <= 60:
        return 0.2, False, days
    return 0.05, False, days


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    'name': 0.22,
    'category': 0.18,
    'description': 0.16,
    'brand': 0.10,
    'distinctive_marks': 0.10,
    'location': 0.10,
    'color': 0.06,
    'date': 0.08,
}

DEFAULT_THRESHOLDS = {'strong': 75, 'possible': 55, 'low': 35}

LABELS = {
    'strong': 'Strong Possible Match',
    'possible': 'Possible Match',
    'low': 'Low Similarity',
    'none': 'No Meaningful Match',
}

FIELD_LABELS = {
    'name': 'item name',
    'category': 'category',
    'description': 'description',
    'brand': 'brand',
    'distinctive_marks': 'identifying marks',
    'location': 'location',
    'color': 'colour',
    'date': 'date',
}


def _has_value(value) -> bool:
    return normalize_text(value) != ''


def classify(score: float, thresholds: dict | None = None) -> str:
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    if score >= t['strong']:
        return 'strong'
    if score >= t['possible']:
        return 'possible'
    if score >= t['low']:
        return 'low'
    return 'none'


def score_pair(lost: dict, found: dict, weights: dict | None = None,
               thresholds: dict | None = None) -> dict:
    """Compare one lost report with one found report.

    Both arguments are dictionaries with keys: item_name, category,
    description, color, brand, distinctive_marks, location, item_date
    (plus optional item_id / user_id which are ignored for scoring).

    Returns a dictionary with score, label, breakdown, reasons, conflicts
    and missing information. The score is a suggestion only.
    """
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    values: dict[str, float] = {}
    reasons: list[str] = []
    conflicts: list[str] = []
    missing: list[str] = []
    penalty = 0.0
    name_sim = 0.0
    category_conflict = False

    # --- Name ---------------------------------------------------------
    if _has_value(lost.get('item_name')) and _has_value(found.get('item_name')):
        sim = text_similarity(lost['item_name'], found['item_name'])
        values['name'] = sim
        name_sim = sim
        if sim >= 0.75:
            reasons.append(f"Item names are very similar ({sim * 100:.0f}%).")
        elif sim >= 0.45:
            reasons.append(f"Item names share keywords ({sim * 100:.0f}%).")
        elif sim < 0.2:
            conflicts.append(
                f"Item names look different ('{lost['item_name']}' vs '{found['item_name']}')."
            )
    else:
        missing.append('item name')

    # --- Category -----------------------------------------------------
    if _has_value(lost.get('category')) and _has_value(found.get('category')):
        cat_a = normalize_text(lost['category'])
        cat_b = normalize_text(found['category'])
        if cat_a == cat_b:
            values['category'] = 1.0
            reasons.append(f"Same category ({lost['category']}).")
        else:
            category_conflict = True
            sim = token_overlap(cat_a, cat_b)
            values['category'] = sim
            conflicts.append(
                f"Different categories ({lost['category']} vs {found['category']})."
            )
            penalty += 0.10
    else:
        missing.append('category')

    # --- Description (TF-IDF cosine) -----------------------------------
    if _has_value(lost.get('description')) and _has_value(found.get('description')):
        sim = tfidf_cosine(lost['description'], found['description'])
        values['description'] = sim
        if sim >= 0.55:
            reasons.append(f"Descriptions are strongly similar ({sim * 100:.0f}%).")
        elif sim >= 0.3:
            reasons.append(f"Descriptions are somewhat similar ({sim * 100:.0f}%).")
        elif sim < 0.1:
            conflicts.append("Descriptions do not share meaningful keywords.")
    else:
        missing.append('description')

    # --- Brand ---------------------------------------------------------
    if _has_value(lost.get('brand')) and _has_value(found.get('brand')):
        sim = text_similarity(lost['brand'], found['brand'])
        values['brand'] = sim
        if sim >= 0.8:
            reasons.append(f"Matching brand ({found['brand']}).")
        elif sim < 0.4:
            conflicts.append(f"Different brands ({lost['brand']} vs {found['brand']}).")
    else:
        missing.append('brand')

    # --- Distinctive marks ---------------------------------------------
    marks_a = lost.get('distinctive_marks')
    marks_b = found.get('distinctive_marks')
    if _has_value(marks_a) and _has_value(marks_b):
        sim = max(tfidf_cosine(marks_a, marks_b), token_overlap(marks_a, marks_b))
        values['distinctive_marks'] = sim
        if sim >= 0.35:
            reasons.append(f"Identifying marks overlap ({sim * 100:.0f}%).")
    else:
        missing.append('distinctive marks')

    # --- Location ------------------------------------------------------
    if _has_value(lost.get('location')) and _has_value(found.get('location')):
        sim, _ = location_similarity(lost['location'], found['location'])
        values['location'] = sim or 0.0
        if sim >= 0.9:
            reasons.append(f"Location matches ({found['location']}).")
        elif sim >= 0.5:
            reasons.append("Locations are close or related.")
    else:
        missing.append('location')

    # --- Colour (supporting evidence only) -----------------------------
    if _has_value(lost.get('color')) and _has_value(found.get('color')):
        sim, conflict = color_similarity(lost['color'], found['color'])
        values['color'] = sim or 0.0
        if conflict:
            conflicts.append(f"Different colours ({lost['color']} vs {found['color']}).")
            penalty += 0.05
        elif sim >= 0.85:
            reasons.append(f"Matching colour ({found['color']}).")
    else:
        missing.append('colour')

    # --- Date ----------------------------------------------------------
    lost_date = lost.get('item_date') or lost.get('date_lost')
    found_date = found.get('item_date') or found.get('date_found')
    if lost_date and found_date:
        sim, conflict, days = date_similarity(lost_date, found_date)
        if sim is not None:
            values['date'] = sim
            if conflict:
                conflicts.append(
                    f"Found date is before the lost date ({days} days)."
                )
                penalty += 0.15
            elif days is not None and sim >= 0.85:
                reasons.append(f"Dates are compatible ({days} day(s) apart).")
    else:
        missing.append('date')

    # --- Weighted, re-normalised total ---------------------------------
    counted = {k: v for k, v in values.items() if k in weights}
    total_weight = sum(weights[k] for k in counted)
    if total_weight <= 0:
        raw = 0.0
    else:
        raw = sum(counted[k] * weights[k] for k in counted) / total_weight
    score = max(0.0, min(100.0, (raw - penalty) * 100))

    # Different categories with different names is a strong signal that the
    # reports are unrelated, no matter how similar the wording is. Cap it at
    # the top of the "low similarity" band instead of allowing a false
    # "possible match".
    if category_conflict and name_sim < 0.55:
        score = min(score, 45.0)

    score = round(score, 1)

    band = classify(score, limits)
    breakdown = []
    for key, weight in weights.items():
        value = values.get(key)
        breakdown.append({
            'factor': key,
            'label': FIELD_LABELS[key],
            'value': None if value is None else round(value, 3),
            'weight': weight,
            'points': None if value is None else round(value * weight * 100 / total_weight, 1) if total_weight else 0.0,
        })

    # A strong score requires at least one strong primary signal
    # (name, category or description). Colour/location alone can never
    # produce a strong match.
    primary = max(values.get('name', 0), values.get('category', 0), values.get('description', 0))
    if score >= limits['strong'] and primary < 0.5:
        band = 'possible'
        conflicts.append(
            "Primary details (name, category, description) are not similar enough "
            "for a strong match; treat this as a weak lead."
        )

    return {
        'score': score,
        'label': LABELS[band],
        'band': band,
        'breakdown': breakdown,
        'reasons': reasons,
        'conflicts': conflicts,
        'missing': sorted(set(missing)),
        'matched_weight': round(total_weight, 3),
    }

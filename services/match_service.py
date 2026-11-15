"""Database-backed match creation / recalculation.

Uses the pure scoring functions from services.matching so the algorithm
itself stays easy to test.
"""
import json

from flask import current_app

import db
from services import matching

INELIGIBLE_STATUSES = ('Returned', 'Claimed', 'Rejected', 'Removed')


def _config(key, fallback):
    try:
        return current_app.config.get(key, fallback)
    except RuntimeError:  # outside app context (tests)
        return fallback


def weights():
    return _config('MATCH_WEIGHTS', matching.DEFAULT_WEIGHTS)


def thresholds():
    return _config('MATCH_THRESHOLDS', matching.DEFAULT_THRESHOLDS)


def min_score():
    return float(_config('MATCH_MIN_SCORE', 30))


def item_is_eligible(item) -> bool:
    return bool(item) and not item.get('is_returned') and item.get('status') not in INELIGIBLE_STATUSES


def _serialise(result):
    return json.dumps({
        'reasons': result['reasons'],
        'conflicts': result['conflicts'],
        'missing': result['missing'],
        'breakdown': result['breakdown'],
        'label': result['label'],
        'band': result['band'],
    }, ensure_ascii=False)


def deserialise(raw):
    if not raw:
        return {'reasons': [], 'conflicts': [], 'missing': [], 'breakdown': []}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {'reasons': [raw], 'conflicts': [], 'missing': [], 'breakdown': []}


def _notify(user_id, match_id, message):
    db.execute(
        "INSERT INTO notifications (user_id, match_id, message) VALUES (%s, %s, %s)",
        (user_id, match_id, message),
    )


def recalculate_for_item(item_id: int) -> list[dict]:
    """Recompute every match involving this report.

    Old match rows for the item are removed first so detail edits never leave
    stale or duplicate records behind.
    """
    item = db.query_one("SELECT * FROM item_reports WHERE item_id = %s", (item_id,))
    if not item:
        return []

    db.execute("DELETE FROM matches WHERE lost_item_id = %s OR found_item_id = %s",
               (item_id, item_id))

    if not item_is_eligible(item):
        return []

    if item['item_type'] == 'Lost':
        candidates = db.query_all(
            """SELECT * FROM item_reports
               WHERE item_type = 'Found' AND is_returned = 0
                 AND status NOT IN ('Returned', 'Claimed', 'Rejected')
                 AND item_id <> %s""",
            (item_id,),
        )
        pairs = [(item, found) for found in candidates]
    else:
        candidates = db.query_all(
            """SELECT * FROM item_reports
               WHERE item_type = 'Lost' AND is_returned = 0
                 AND status NOT IN ('Returned', 'Claimed', 'Rejected')
                 AND item_id <> %s""",
            (item_id,),
        )
        pairs = [(lost, item) for lost in candidates]

    created = []
    for lost, found in pairs:
        result = matching.score_pair(lost, found, weights(), thresholds())
        if result['score'] < min_score():
            continue
        match_id = db.execute(
            """INSERT INTO matches
                   (lost_item_id, found_item_id, match_score, match_reasons, status)
               VALUES (%s, %s, %s, %s, 'Active')""",
            (lost['item_id'], found['item_id'], result['score'], _serialise(result)),
        )
        created.append({'match_id': match_id, 'score': result['score'],
                        'lost': lost, 'found': found, 'result': result})
        message = (
            f"Possible match ({result['score']}%): "
            f"'{lost['item_name']}' may match '{found['item_name']}'."
        )
        _notify(lost['user_id'], match_id, message)
        if found['user_id'] != lost['user_id']:
            _notify(found['user_id'], match_id, message)

    return created


def recalculate_all() -> int:
    rows = db.query_all("SELECT item_id FROM item_reports")
    for row in rows:
        recalculate_for_item(row['item_id'])
    return len(rows)


def get_matches_for_item(item_id: int) -> list[dict]:
    """Return enriched matches for one report (unfiltered by user)."""
    rows = db.query_all(
        """SELECT m.*, l.item_name AS lost_name, f.item_name AS found_name,
                  l.user_id AS lost_user_id, f.user_id AS found_user_id
           FROM matches m
           JOIN item_reports l ON l.item_id = m.lost_item_id
           JOIN item_reports f ON f.item_id = m.found_item_id
           WHERE m.lost_item_id = %s OR m.found_item_id = %s
           ORDER BY m.match_score DESC""",
        (item_id, item_id),
    )
    return _enrich(rows)


def get_matches_for_user(user_id: int, limit: int | None = None) -> list[dict]:
    sql = """SELECT m.*, l.item_name AS lost_name, f.item_name AS found_name,
                    l.user_id AS lost_user_id, f.user_id AS found_user_id
             FROM matches m
             JOIN item_reports l ON l.item_id = m.lost_item_id
             JOIN item_reports f ON f.item_id = m.found_item_id
             WHERE (l.user_id = %s OR f.user_id = %s)
               AND m.status = 'Active'
               AND l.is_returned = 0 AND f.is_returned = 0
             ORDER BY m.match_score DESC, m.created_at DESC"""
    params = [user_id, user_id]
    if limit:
        sql += " LIMIT %s"
        params.append(int(limit))
    return _enrich(db.query_all(sql, tuple(params)))


def _enrich(rows):
    for row in rows:
        row['details'] = deserialise(row.get('match_reasons'))
        row['match_score'] = float(row['match_score'])
    return rows


def count_unread_notifications(user_id: int) -> int:
    row = db.query_one(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = %s AND is_read = 0",
        (user_id,),
    )
    return int(row['c']) if row else 0


def recent_notifications(user_id: int, limit: int = 6) -> list[dict]:
    return db.query_all(
        """SELECT n.*, m.match_score, m.lost_item_id, m.found_item_id
           FROM notifications n
           LEFT JOIN matches m ON m.match_id = n.match_id
           WHERE n.user_id = %s
           ORDER BY n.is_read ASC, n.created_at DESC
           LIMIT %s""",
        (user_id, int(limit)),
    )


def mark_notifications_read(user_id: int) -> None:
    db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = %s", (user_id,))

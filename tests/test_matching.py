"""Pure unit tests for the smart matching algorithm (no database needed)."""
from services import matching


def lost_item(**overrides):
    base = {
        'item_name': 'Black leather wallet',
        'category': 'Accessories',
        'description': 'Black leather wallet with a student ID card inside, lost near the library desks',
        'color': 'Black',
        'brand': 'Fossil',
        'distinctive_marks': 'Small scratch on the corner and a flower sticker inside',
        'location': 'Library',
        'item_date': '2026-09-20',
    }
    base.update(overrides)
    return base


def found_item(**overrides):
    base = {
        'item_name': 'Black wallet found',
        'category': 'Accessories',
        'description': 'Found a black leather wallet near the library with an ID card inside',
        'color': 'Black',
        'brand': 'Fossil',
        'distinctive_marks': 'Has a small scratch and a flower sticker inside',
        'location': 'Library',
        'item_date': '2026-09-21',
    }
    base.update(overrides)
    return base


def test_normalize_and_tokenize():
    assert matching.normalize_text('  Black   WALLET!! ') == 'black wallet'
    tokens = matching.tokenize('Black leather wallets found near the library')
    assert 'black' in tokens
    assert 'wallet' in tokens
    assert 'library' in tokens
    assert 'found' not in tokens  # stopword


def test_tfidf_identical_text_is_one():
    assert matching.tfidf_cosine('blue water bottle with sticker', 'blue water bottle with sticker') == 1.0


def test_tfidf_unrelated_text_is_low():
    score = matching.tfidf_cosine('blue water bottle', 'mathematics notebook with formulas')
    assert score < 0.2


def test_strong_match_scores_high():
    result = matching.score_pair(lost_item(), found_item())
    assert result['score'] >= 75
    assert result['band'] == 'strong'
    assert any('category' in r.lower() for r in result['reasons'])


def test_same_colour_unrelated_items_do_not_score_strong():
    lost = lost_item(
        item_name='Black leather wallet', category='Accessories',
        description='Black leather wallet with an ID card inside',
        brand='Fossil', distinctive_marks='flower sticker inside',
        location='Library',
    )
    found = found_item(
        item_name='Black umbrella', category='Other',
        description='A large black umbrella found in the sports ground',
        brand='Popy', distinctive_marks=None, location='Sports Ground',
    )
    result = matching.score_pair(lost, found)
    assert result['score'] < 55
    assert result['band'] != 'strong'
    assert any('colour' in c.lower() or 'categor' in c.lower() for c in result['conflicts'])


def test_missing_information_never_counts_as_a_match():
    lost = {
        'item_name': 'Water bottle', 'category': 'Water Bottles',
        'description': 'Pink bottle with a flower sticker',
        'color': None, 'brand': None, 'distinctive_marks': None,
        'location': None, 'item_date': None,
    }
    found = {
        'item_name': 'Water bottle', 'category': 'Water Bottles',
        'description': 'Pink bottle with a flower sticker',
        'color': 'Pink', 'brand': None, 'distinctive_marks': None,
        'location': 'Library', 'item_date': '2026-09-21',
    }
    result = matching.score_pair(lost, found)
    assert 'colour' in result['missing']
    assert 'brand' in result['missing']
    assert 'location' in result['missing']
    # Colour must not be counted in the weighted total.
    colour_row = next(row for row in result['breakdown'] if row['factor'] == 'color')
    assert colour_row['value'] is None


def test_different_categories_are_penalised():
    lost = lost_item(category='Electronics', item_name='Blue laptop bag')
    found = found_item(category='Water Bottles', item_name='Blue bottle')
    result = matching.score_pair(lost, found)
    assert result['score'] < 50
    assert any('Different categories' in c for c in result['conflicts'])


def test_found_date_before_lost_date_is_a_conflict():
    lost = lost_item(item_date='2026-09-25')
    found = found_item(item_date='2026-09-10')
    result = matching.score_pair(lost, found)
    assert any('before the lost date' in c for c in result['conflicts'])
    assert result['score'] < 70


def test_color_families_are_understood():
    score, conflict = matching.color_similarity('Navy', 'Blue')
    assert score >= 0.9 and conflict is False
    score, conflict = matching.color_similarity('Black', 'Pink')
    assert score == 0.0 and conflict is True


def test_location_zones_are_understood():
    score, _ = matching.location_similarity('Block A', 'Block B')
    assert score >= 0.8
    score, _ = matching.location_similarity('Library', 'Parking')
    assert score < 0.5


def test_colour_alone_can_never_be_strong():
    lost = lost_item(
        item_name='Wallet', category='Accessories', description='A wallet',
        brand=None, distinctive_marks=None, location='Library',
        item_date='2026-09-20',
    )
    found = found_item(
        item_name='Backpack', category='Bags & Luggage', description='A backpack',
        brand=None, distinctive_marks=None, location='Sports Ground',
        item_date='2026-09-20',
    )
    result = matching.score_pair(lost, found)
    assert result['band'] != 'strong'


def test_weights_are_configurable():
    weights = {k: 0.0 for k in matching.DEFAULT_WEIGHTS}
    weights['name'] = 1.0
    result = matching.score_pair(lost_item(), found_item(item_name='Black leather wallet'),
                                 weights=weights)
    assert result['score'] > 70
    assert result['matched_weight'] == 1.0


def test_thresholds_follow_configuration():
    result = matching.score_pair(lost_item(), found_item(), thresholds={'strong': 101, 'possible': 50, 'low': 20})
    assert result['band'] != 'strong'


def test_reasons_and_breakdown_are_explainable():
    result = matching.score_pair(lost_item(), found_item())
    assert result['reasons']
    assert len(result['breakdown']) == len(matching.DEFAULT_WEIGHTS)
    assert all('label' in row and 'weight' in row for row in result['breakdown'])
    assert result['label'] in ('Strong Possible Match', 'Possible Match', 'Low Similarity', 'No Meaningful Match')

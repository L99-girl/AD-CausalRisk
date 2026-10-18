"""Observed visit series with explicit gaps, units and no imputation or prediction."""
import math

METRICS = {
    'mmse': {'label': 'MMSE', 'unit': '分', 'minimum': 0, 'maximum': 30, 'digits': 0},
    'cdr': {'label': 'Global CDR', 'unit': '分', 'minimum': 0, 'maximum': 3, 'digits': 1},
    'nwbv': {'label': 'nWBV', 'unit': '比例', 'minimum': 0, 'maximum': 1, 'digits': 6},
}


class TimelineError(ValueError):
    pass


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def build_timeline(visits, metric='mmse'):
    if metric not in METRICS or not isinstance(visits, list) or len(visits) > 1000:
        raise TimelineError('TIMELINE_INPUT')
    rule = METRICS[metric]
    rows = []
    for position, visit in enumerate(visits):
        if not isinstance(visit, dict) or type(visit.get('visit')) is not int or visit['visit'] < 1:
            raise TimelineError('VISIT_ID')
        day, value = visit.get('days_from_first_mri'), visit.get(metric)
        date_ok = finite(day) and day >= 0
        value_ok = finite(value) and rule['minimum'] <= value <= rule['maximum']
        if metric == 'mmse' and value_ok:
            value_ok = value == int(value)
        if metric == 'cdr' and value_ok:
            value_ok = value in (0, .5, 1, 2, 3)
        issue = 'INVALID_TIME' if not date_ok else 'MISSING_VALUE' if value is None else 'INVALID_VALUE' if not value_ok else None
        rows.append({'visit': visit['visit'], 'day': day if date_ok else None,
                     'value': value if value_ok else None, 'issue': issue, '_position': position})
    # An unknown-time row cannot be placed in a chronology. Keep it in the table,
    # and disable connectors rather than guessing which segment it interrupts.
    rows.sort(key=lambda row: (row['day'] is None, row['day'] if row['day'] is not None else 0, row['_position']))
    for row in rows:row.pop('_position')
    points = [dict(row) for row in rows if row['issue'] is None]
    repeated_days = sorted({row['day'] for row in rows if row['day'] is not None
                            and sum(other['day'] == row['day'] for other in rows) > 1})
    connectors = []
    if all(row['day'] is not None for row in rows) and len({row['visit'] for row in rows}) == len(rows):
        for left, right in zip(rows, rows[1:]):
            if (left['issue'] is None and right['issue'] is None and left['day'] < right['day']
                    and left['day'] not in repeated_days and right['day'] not in repeated_days):
                connectors.append({'from_visit': left['visit'], 'to_visit': right['visit']})
    extent = [row['day'] for row in rows if row['day'] is not None]
    start, end = (min(extent), max(extent)) if extent else (None, None)
    return {'metric': metric, **rule, 'time_unit': 'days_from_first_mri', 'rows': rows, 'points': points,
            'connectors': connectors, 'total_visits': len(rows), 'observed_count': len(points),
            'missing_count': sum(visit.get(metric) is None for visit in visits),
            'invalid_count': sum(row['issue'] in ('INVALID_TIME', 'INVALID_VALUE') for row in rows),
            'duplicate_visit_ids': len({row['visit'] for row in rows}) != len(rows),
            'repeated_days': repeated_days, 'start_day': start, 'end_day': end,
            'span_days': end-start if extent else None,
            'net_observed_change': points[-1]['value']-points[0]['value'] if len(points) >= 2 and not repeated_days and not any(row['day'] is None for row in rows) else None,
            'imputed_values': 0, 'predictions': None, 'uncertainty': None,
            'connector_meaning': 'Optional visual guide between adjacent observed visits only; not interpolation, daily observations or prediction'}

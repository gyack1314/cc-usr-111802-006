"""把两个已知时点的结论差异归因到来源、覆盖或分析口径。

归因类别：
- 观测：记录版次与覆盖元数据均未变，仅数值变化（如重新标定后的数值修订）；
- 覆盖：产品版本、站点集合、迁站链接、共同参照、质量元数据发生变化，
  或记录在新时点出现/消失（观测网络调整）；
- 分析口径：参照值或区域规则变化（规则阈值、方向、动作、参照记录修订）。
"""
from .evidence import records
from .comparability import COVERAGE_FIELDS

OBSERVATION = '观测'
COVERAGE = '覆盖'
CALIBER = '分析口径'
ADDED = '新增'
WITHDRAWN = '停用'
UNCHANGED = '无变化'


def _index(rows):
    return {row['id']: row for row in rows}


def _observation_cause(before, after):
    before_payload = before['payload']
    after_payload = after['payload']
    if before['revision'] != after['revision']:
        coverage_changed = any(
            before_payload.get(field) != after_payload.get(field) for field in COVERAGE_FIELDS
        )
        if coverage_changed:
            return COVERAGE
        if before_payload.get('value') != after_payload.get('value'):
            return OBSERVATION
        return COVERAGE
    if before_payload.get('value') != after_payload.get('value'):
        return OBSERVATION
    return UNCHANGED


def _payload_cause(before, after):
    """参照与规则记录：版次或正文变化统一计为分析口径。"""
    if before['revision'] != after['revision'] or before['payload'] != after['payload']:
        return CALIBER
    return UNCHANGED


def attribute(db, before_known_at, after_known_at):
    """比较两个已知时点可见的全部记录，逐条给出归因。"""
    grouped = {}
    for kind, label in (
        ('observation', 'observation'),
        ('reference', 'reference'),
        ('rule', 'rule'),
    ):
        before_rows = _index(records(db, kind, before_known_at))
        after_rows = _index(records(db, kind, after_known_at))
        entries = []
        for record_id in sorted(set(before_rows) | set(after_rows)):
            before = before_rows.get(record_id)
            after = after_rows.get(record_id)
            if before is None:
                entries.append({
                    'kind': label, 'id': record_id, 'cause': COVERAGE,
                    'note': ADDED, 'before_revision': None,
                    'after_revision': after['revision'],
                })
                continue
            if after is None:
                entries.append({
                    'kind': label, 'id': record_id, 'cause': COVERAGE,
                    'note': WITHDRAWN, 'before_revision': before['revision'],
                    'after_revision': None,
                })
                continue
            if kind == 'observation':
                cause = _observation_cause(before, after)
            else:
                cause = _payload_cause(before, after)
            entries.append({
                'kind': label, 'id': record_id, 'cause': cause,
                'note': None,
                'before_revision': before['revision'],
                'after_revision': after['revision'],
            })
        grouped[label] = entries

    counts = {OBSERVATION: 0, COVERAGE: 0, CALIBER: 0, UNCHANGED: 0}
    for entries in grouped.values():
        for entry in entries:
            counts[entry['cause']] += 1
    return {
        'before_known_at': before_known_at,
        'after_known_at': after_known_at,
        'records': grouped,
        'counts': counts,
    }

"""跨期趋势比较前的可比性核对。

四类闸门：
- 产品版本：相邻时期必须来自同一产品名称与处理版次（如卫星轨道处理版本）；
- 站点覆盖：相邻时期的站点集合须一致，差异只能由登记的迁站延续链接解释；
- 共同参照：相邻时期必须挂接同一基准/参照框架；
- 测量质量：每期质量等级须达标且不含阻断标记。

任一双时期闸门不通过即形成区间断裂，质量不达标时期直接剔除；
断裂与剔除统一列入无法判定区间，不参与趋势计算。
"""
from .evidence import records

PRODUCT = '产品版本'
COVERAGE = '站点覆盖'
DATUM = '共同参照'
QUALITY = '测量质量'

ACCEPTABLE_GRADES = ('A', 'B')
COVERAGE_FIELDS = ('product', 'network', 'stations', 'station_links', 'datum', 'quality')


def period_of(record):
    """时期标识优先取 payload.period，缺省退回 valid_from 的年份。"""
    period = record['payload'].get('period')
    if period is None:
        period = record['valid_from'][:4]
    return str(period)


def series(db, known_at, metric, region, start=None, end=None):
    """取已知时点可见的指定海域指标年度序列，按时期排序。"""
    points = []
    for record in records(db, 'observation', known_at):
        payload = record['payload']
        if payload.get('metric') != metric or payload.get('region') != region:
            continue
        period = period_of(record)
        if start is not None and period < str(start):
            continue
        if end is not None and period > str(end):
            continue
        points.append((period, record))
    points.sort(key=lambda item: item[0])
    return points


def _product_id(payload):
    product = payload.get('product')
    if not isinstance(product, dict):
        return None
    name = product.get('name')
    version = product.get('version')
    if name is None or version is None:
        return None
    return {'name': name, 'version': version}


def _stations(payload):
    return frozenset(payload.get('stations') or ())


def check_transition(earlier, later):
    """核对两个相邻时期之间的产品版本、共同参照、站点覆盖三道闸门。

    返回 (原因列表, 明细, 共同站点列表)；原因为空表示双时期可比。
    迁站延续链接 station_links 位于后一时期 payload：新站 -> 前身老站。
    """
    a = earlier['payload']
    b = later['payload']
    reasons = []
    detail = {}

    before_product = _product_id(a)
    after_product = _product_id(b)
    if before_product is None or after_product is None:
        reasons.append(PRODUCT)
        detail[PRODUCT] = '产品版本信息缺失'
    elif before_product != after_product:
        reasons.append(PRODUCT)
        detail[PRODUCT] = {'before': before_product, 'after': after_product}

    before_datum = a.get('datum')
    after_datum = b.get('datum')
    if not before_datum or not after_datum:
        reasons.append(DATUM)
        detail[DATUM] = '共同参照信息缺失'
    elif before_datum != after_datum:
        reasons.append(DATUM)
        detail[DATUM] = {'before': before_datum, 'after': after_datum}

    before_stations = _stations(a)
    after_stations = _stations(b)
    links = b.get('station_links') or {}
    predecessors = set(links.values())
    added = sorted(
        station for station in after_stations - before_stations
        if links.get(station) not in before_stations
    )
    removed = sorted(
        station for station in before_stations - after_stations
        if station not in predecessors
    )
    common = sorted(before_stations & after_stations)
    if added or removed:
        reasons.append(COVERAGE)
        detail[COVERAGE] = {'common': common, 'added': added, 'removed': removed}

    return reasons, detail, common


def check_quality(record, acceptable_grades=ACCEPTABLE_GRADES):
    """单期测量质量闸门，返回 (是否通过, 不通过说明)；问题全部保留以便评审。"""
    quality = record['payload'].get('quality')
    if not isinstance(quality, dict):
        return False, '测量质量信息缺失'
    problems = []
    grade = quality.get('grade')
    if grade not in acceptable_grades:
        problems.append(f"质量等级 {grade!r} 不在可接受范围 {list(acceptable_grades)}")
    flags = quality.get('flags') or []
    if flags:
        problems.append(f"存在阻断标记 {sorted(flags)}")
    if problems:
        return False, '；'.join(problems)
    return True, None


def _period_row(period, record, quality_ok, quality_message):
    payload = record['payload']
    return {
        'period': period,
        'record_id': record['id'],
        'revision': record['revision'],
        'product': _product_id(payload),
        'datum': payload.get('datum'),
        'stations': sorted(_stations(payload)),
        'station_links': payload.get('station_links') or {},
        'quality': payload.get('quality'),
        'quality_ok': quality_ok,
        'quality_message': quality_message,
        'source_sha256': record['source']['sha256'],
    }


def assess(db, known_at, metric, region, start=None, end=None,
           acceptable_grades=ACCEPTABLE_GRADES):
    """执行全部可比性核对并切分可比区段。

    返回逐期核对行、可比区段（仅含时期与记录）、无法判定区间。
    """
    points = series(db, known_at, metric, region, start, end)
    period_rows = []
    bad_quality_periods = set()
    undeterminable = []

    for period, record in points:
        ok, message = check_quality(record, acceptable_grades)
        period_rows.append(_period_row(period, record, ok, message))
        if not ok:
            bad_quality_periods.add(period)
            undeterminable.append({
                'type': '时期剔除',
                'start': period,
                'end': period,
                'reasons': [QUALITY],
                'detail': message,
            })

    breaks = {}
    for (earlier_period, earlier), (later_period, later) in zip(points, points[1:]):
        reasons, detail, _common = check_transition(earlier, later)
        if reasons:
            breaks[(earlier_period, later_period)] = (reasons, detail)
            undeterminable.append({
                'type': '区间断裂',
                'start': earlier_period,
                'end': later_period,
                'reasons': reasons,
                'detail': detail,
            })

    segments = []
    current = []
    for period, record in points:
        if period in bad_quality_periods:
            if current:
                segments.append(current)
                current = []
            continue
        if current and (current[-1][0], period) in breaks:
            segments.append(current)
            current = []
        current.append((period, record))
    if current:
        segments.append(current)

    return {
        'known_at': known_at,
        'metric': metric,
        'region': region,
        'periods': period_rows,
        'segments': segments,
        'undeterminable': undeterminable,
    }

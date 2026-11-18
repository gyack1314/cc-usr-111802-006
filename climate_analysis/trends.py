"""仅在通过可比性核对的区段内计算趋势。

无法判定区间保持无趋势结论；观测网络调整导致的断裂与质量剔除
在 comparability.assess 的输出中单独保留，由本模块原样透出，
避免把观测网络变化混进线性趋势。
"""
from .comparability import assess


def _slope(pairs):
    """对 (时期序号, 数值) 做普通最小二乘，无第三方依赖。"""
    count = len(pairs)
    if count < 2:
        return None
    mean_x = sum(x for x, _ in pairs) / count
    mean_y = sum(y for _, y in pairs) / count
    denominator = sum((x - mean_x) ** 2 for x, _ in pairs)
    if denominator == 0:
        return None
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    return numerator / denominator


def _period_index(period):
    """把时期转为可计算的序号：四位年份取整数，否则保留原值不计算。"""
    text = str(period)
    if len(text) == 4 and text.isdigit():
        return int(text)
    return None


def analyze(db, known_at, metric, region, start=None, end=None):
    """生成跨期趋势分析：可比区段给趋势，其余区间明确无法判定。"""
    result = assess(db, known_at, metric, region, start, end)
    trends = []
    for index, segment in enumerate(result['segments'], start=1):
        periods = [period for period, _ in segment]
        pairs = []
        for period, record in segment:
            x_value = _period_index(period)
            y_value = record['payload'].get('value')
            if x_value is None or not isinstance(y_value, (int, float)):
                pairs = None
                break
            pairs.append((x_value, float(y_value)))
        entry = {
            'segment_index': index,
            'start': periods[0],
            'end': periods[-1],
            'periods': periods,
            'sources': sorted({record['source']['sha256'] for _, record in segment}),
        }
        if pairs is None or len(pairs) < 2:
            entry.update({'status': '样本不足', 'trend_per_period': None})
        else:
            entry.update({
                'status': '可比趋势',
                'trend_per_period': _slope(pairs),
                'unit': segment[0][1]['payload'].get('unit'),
            })
        trends.append(entry)

    result['trends'] = trends
    result['summary'] = {
        'comparable_segments': len([item for item in trends if item['status'] == '可比趋势']),
        'undeterminable_intervals': len(result['undeterminable']),
        'excluded_periods': sorted(
            item['start'] for item in result['undeterminable'] if item['type'] == '时期剔除'
        ),
    }
    return result

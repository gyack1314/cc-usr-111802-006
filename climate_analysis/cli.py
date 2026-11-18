"""从本地合成资料形成已知时间的报告、跨期趋势与差异归因。"""
import argparse
import json
from pathlib import Path

from .evidence import connect, receive
from .report import generate, difference
from .trends import analyze
from .attribution import attribute


def _load(path):
    data = json.loads(Path(path).read_text(encoding='utf8'))
    db = connect(':memory:')
    for doc in data['documents']:
        receive(db, doc)
    return db, data


def _print(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _run_inspect(data, db, arguments):
    a, b = [generate(db, t) for t in data['known_at']]
    _print({'before': a, 'after': b, 'change': difference(a, b)})


def _run_trend(data, db, arguments):
    snapshots = arguments.known_at or data['known_at']
    output = []
    for known_at in snapshots:
        output.append(analyze(
            db, known_at, arguments.metric, arguments.region,
            arguments.start, arguments.end,
        ))
    _print({'snapshots': output})


def _run_attribute(data, db, arguments):
    before, after = arguments.known_at if arguments.known_at else data['known_at']
    _print(attribute(db, before, after))


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)

    inspect_parser = subparsers.add_parser('inspect', help='两时点单期指标报告')
    inspect_parser.add_argument('input')
    inspect_parser.set_defaults(handler=_run_inspect, needs_data=True)

    trend_parser = subparsers.add_parser('trend', help='跨期可比性核对与可比区段趋势')
    trend_parser.add_argument('input')
    trend_parser.add_argument('--metric', required=True)
    trend_parser.add_argument('--region', required=True)
    trend_parser.add_argument('--start')
    trend_parser.add_argument('--end')
    trend_parser.add_argument('--known-at', nargs='+', help='覆盖数据文件中的已知时点')
    trend_parser.set_defaults(handler=_run_trend, needs_data=True)

    attribute_parser = subparsers.add_parser('attribute', help='两时点差异的观测/覆盖/口径归因')
    attribute_parser.add_argument('input')
    attribute_parser.add_argument('--known-at', nargs=2)
    attribute_parser.set_defaults(handler=_run_attribute, needs_data=True)

    arguments = parser.parse_args()
    db, data = _load(arguments.input)
    try:
        arguments.handler(data, db, arguments)
    finally:
        db.close()


if __name__ == '__main__':
    main()

"""验证跨期可比性闸门、可比区段趋势、差异归因与旧报告可复现性。"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from climate_analysis.attribution import attribute, OBSERVATION, COVERAGE, CALIBER, UNCHANGED
from climate_analysis.comparability import (
    PRODUCT, COVERAGE as COVERAGE_REASON, DATUM, QUALITY, check_transition, check_quality,
)
from climate_analysis.evidence import connect, receive
from climate_analysis.report import generate
from climate_analysis.trends import analyze

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = json.loads((ROOT / 'data' / 'network-change.json').read_text(encoding='utf8'))
T1, T2 = SCENARIO['known_at']


def load(db, only_before=None):
    for doc in SCENARIO['documents']:
        if only_before is not None and doc['received_at'] > only_before:
            continue
        receive(db, doc)


class ComparabilityGates(unittest.TestCase):
    def setUp(self):
        self.db = connect(':memory:')
        load(self.db)

    def tearDown(self):
        self.db.close()

    def test_first_snapshot_splits_at_network_change(self):
        result = analyze(self.db, T1, 'sea_level', 'ocean-A')
        # 两个真实可比区段 + 一个单时期样本不足区段
        comparable = [item for item in result['trends'] if item['status'] == '可比趋势']
        self.assertEqual([(item['start'], item['end']) for item in comparable],
                         [('2019', '2021'), ('2022', '2023')])
        self.assertAlmostEqual(comparable[0]['trend_per_period'], 1.0)
        self.assertAlmostEqual(comparable[1]['trend_per_period'], 1.5)

        breaks = {(item['start'], item['end']): item for item in result['undeterminable']
                  if item['type'] == '区间断裂'}
        self.assertIn(('2021', '2022'), breaks)
        self.assertEqual(set(breaks[('2021', '2022')]['reasons']),
                         {PRODUCT, DATUM, COVERAGE_REASON})
        detail = breaks[('2021', '2022')]['detail']
        self.assertEqual(detail[PRODUCT]['before']['version'], 'v3p0')
        self.assertEqual(detail[PRODUCT]['after']['name'], '验潮整编')
        self.assertEqual(detail[DATUM], {'before': 'D1990', 'after': 'D2020'})
        self.assertEqual(detail[COVERAGE_REASON]['removed'], ['S1', 'S2'])
        self.assertEqual(detail[COVERAGE_REASON]['added'], ['S4', 'S5'])

    def test_quality_gate_excludes_defective_period(self):
        result = analyze(self.db, T1, 'sea_level', 'ocean-A')
        excluded = [item for item in result['undeterminable'] if item['type'] == '时期剔除']
        self.assertEqual([(item['start'], item['reasons']) for item in excluded],
                         [('2024', [QUALITY])])
        self.assertIn('C', excluded[0]['detail'])
        period_2024 = next(row for row in result['periods'] if row['period'] == '2024')
        self.assertFalse(period_2024['quality_ok'])
        self.assertIn('gap_interp', period_2024['quality_message'])
        # 剔除时期不得出现在任何趋势区段
        for trend in result['trends']:
            self.assertNotIn('2024', trend['periods'])

    def test_reprocessing_merges_segments_via_relocation_link(self):
        result = analyze(self.db, T2, 'sea_level', 'ocean-A')
        comparable = [item for item in result['trends'] if item['status'] == '可比趋势']
        self.assertEqual(len(comparable), 1)
        self.assertEqual(comparable[0]['periods'], ['2019', '2020', '2021', '2022', '2023'])
        # 2021->2022 站点集合不同，仅靠登记的 S2->S4 迁站链接保持可比
        self.assertNotIn(
            ('2021', '2022'),
            {(item['start'], item['end']) for item in result['undeterminable']},
        )
        self.assertAlmostEqual(comparable[0]['trend_per_period'], 2.4)
        # 质量缺陷时期在重处理后依旧无法判定，不被新资料洗白
        self.assertEqual(result['summary']['excluded_periods'], ['2024'])

    def test_period_window_filter(self):
        result = analyze(self.db, T2, 'sea_level', 'ocean-A', start='2020', end='2022')
        self.assertEqual([row['period'] for row in result['periods']], ['2020', '2021', '2022'])
        self.assertEqual(result['trends'][0]['periods'], ['2020', '2021', '2022'])

    def test_transition_helpers(self):
        from climate_analysis.evidence import records
        rows = {record['id']: record for record in records(self.db, 'observation', T2)}
        reasons, detail, common = check_transition(rows['obs-2021'], rows['obs-2022'])
        self.assertEqual(reasons, [])
        self.assertEqual(common, ['S1', 'S3'])

        # 未登记迁站链接的站点变化必须判为覆盖断裂
        unlinked = json.loads(json.dumps(rows['obs-2022']))
        unlinked['payload']['station_links'] = {}
        reasons, _, _ = check_transition(rows['obs-2021'], unlinked)
        self.assertIn(COVERAGE_REASON, reasons)

        ok, _ = check_quality(rows['obs-2023'])
        self.assertTrue(ok)
        # t2 下 2024 仍为 r1 的 C 级记录
        bad = next(record for record in records(self.db, 'observation', T2)
                   if record['id'] == 'obs-2024')
        ok, message = check_quality(bad)
        self.assertFalse(ok)
        self.assertIn('gap_interp', message)


class ReprocessingReproducibility(unittest.TestCase):
    def test_old_report_fingerprint_survives_reprocessing(self):
        db = connect(':memory:')
        load(db, only_before=T1)
        old_report = generate(db, T1)
        old_trend = analyze(db, T1, 'sea_level', 'ocean-A')
        load(db)  # 之后取得的重处理资料入库
        repeated_report = generate(db, T1)
        repeated_trend = analyze(db, T1, 'sea_level', 'ocean-A')
        self.assertEqual(repeated_report['fingerprint'], old_report['fingerprint'])
        self.assertEqual(
            [(item['start'], item['end'], item['status']) for item in repeated_trend['trends']],
            [(item['start'], item['end'], item['status']) for item in old_trend['trends']],
        )
        db.close()

    def test_new_snapshot_uses_reprocessed_evidence(self):
        db = connect(':memory:')
        load(db)
        t2 = analyze(db, T2, 'sea_level', 'ocean-A')
        revisions = {row['period']: row['revision'] for row in t2['periods']}
        self.assertEqual([revisions[year] for year in ('2019', '2022', '2025')],
                         ['r2', 'r2', 'r2'])
        self.assertEqual(revisions['2024'], 'r1')
        db.close()


class Attribution(unittest.TestCase):
    def setUp(self):
        self.db = connect(':memory:')
        load(self.db)

    def tearDown(self):
        self.db.close()

    def test_causes(self):
        result = attribute(self.db, T1, T2)
        causes = {entry['id']: entry for entries in result['records'].values() for entry in entries}
        # 产品/基准/站点元数据变化 -> 覆盖
        for record_id in ('obs-2019', 'obs-2022', 'obs-2023'):
            self.assertEqual(causes[record_id]['cause'], COVERAGE)
        # 同口径仅数值修订 -> 观测
        self.assertEqual(causes['obs-2025']['cause'], OBSERVATION)
        # 未修订记录保持无变化
        self.assertEqual(causes['obs-2024']['cause'], UNCHANGED)
        # 参照与规则变化 -> 分析口径
        self.assertEqual(causes['ref-1']['cause'], CALIBER)
        self.assertEqual(causes['rule-1']['cause'], CALIBER)
        self.assertEqual(causes['ref-2']['cause'], UNCHANGED)
        self.assertEqual(result['counts'],
                         {OBSERVATION: 1, COVERAGE: 5, CALIBER: 2, UNCHANGED: 2})


class CommandLine(unittest.TestCase):
    def test_trend_and_attribute_commands(self):
        for command in (
            ['trend', 'data/network-change.json', '--metric', 'sea_level', '--region', 'ocean-A'],
            ['attribute', 'data/network-change.json'],
        ):
            completed = subprocess.run(
                [sys.executable, '-m', 'climate_analysis.cli', *command],
                cwd=ROOT, capture_output=True, text=True, check=True,
            )
            payload = json.loads(completed.stdout)
            self.assertTrue(payload)


if __name__ == '__main__':
    unittest.main()

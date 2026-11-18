# 海平面海域指标分析

项目保存海平面海域的来源版次，按资料取得时间比较单期指标并给出区域规则判断。evidence 保存来源，metrics 计算同口径偏离，context 解释当前区域规则，report 保存报告。样本是合成数据。

跨期分析另由三个模块承担，避免把观测网络变化算进趋势：

- comparability：比较指定海域与时期前，逐期核对产品版本（卫星轨道处理版次）、站点覆盖（含迁站延续链接）、共同参照、测量质量四道闸门，切分可比区段与无法判定区间。
- trends：只在可比区段内做最小二乘趋势；质量不达标时期剔除，网络断裂区间单列，不给趋势数。
- attribution：把两个已知时点的结论差异归因到观测（同口径数值修订）、覆盖（产品/站点/基准/质量元数据变化）或分析口径（参照与规则变化）。

较晚取得的重处理资料以新 revision 修订历史记录；`known_at` 截止机制保证旧报告仍按当时证据复现（指纹不变），新分析再采用重处理后的证据，评审可对照两时点的区段与归因。

Python 3.11 以上，在项目根目录执行：

    python -m unittest discover -s tests -v
    python -m compileall -q climate_analysis tests
    python -m climate_analysis.cli inspect data/example.json
    python -m climate_analysis.cli trend data/network-change.json --metric sea_level --region ocean-A
    python -m climate_analysis.cli attribute data/network-change.json

`trend` 可用 `--start`、`--end` 限定时期，用 `--known-at` 指定一个或多个复现时点；`attribute` 用 `--known-at 旧时点 新时点` 指定比较两端。数据约定见 docs/data-contract.md。

Dockerfile 可在 Linux 容器运行：docker build -t climate-analysis-006 .；docker run --rm climate-analysis-006。

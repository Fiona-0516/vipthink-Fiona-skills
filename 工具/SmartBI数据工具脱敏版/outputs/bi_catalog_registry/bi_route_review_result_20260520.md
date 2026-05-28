# BI Route Index P0 Review 结果

## 当前产物

- Mode: data-audit / decision-review
- 问题契约: 判断 P0 route index 是否足以支撑 AI 从业务问题定位候选报表、拿 report_id、看字段和筛选器风险，并生成 dry-run 级取数计划。
- 数据源: 三份 BI profile JSON + SmartBI report_id registry + route index。
- 输出目标: 给出是否可进入下一步应用、限制条件和修复项。

## 口径与数据检查

- 总 profile 数: 407
- registry report_id 数: 499
- 匹配数量 / 匹配率: 401 / 98.53%
- path 匹配: 401
- alias/name 匹配: 0
- unmatched: 6
- ambiguous: 0

### 类型能力边界

| registry type | total | with report_id | with dry-run plan | 判断 |
|---|---:|---:|---:|---|
| SIMPLE_REPORT | 102 | 102 | 0 | 仅可定位，不可用当前 CLI run 下载 |
| SPREADSHEET_REPORT | 299 | 299 | 299 | 可进入 SmartBI CLI dry-run |
| unmatched | 6 | 0 | 0 | 需补 catalog/profile 匹配 |

### 风险分布

| risk_flag | count | 解释 |
|---|---:|---|
| inspect_workbook_shape_before_analysis | 289 | 表可能是透视/看板格式，不能直接当底表分析。 |
| has_filter_safety_limits | 137 | 存在不能安全自动改写的筛选器。 |
| manual_or_default_only_filter | 126 | 存在只能默认或需要人工业务值的筛选器。 |
| registry_type_SIMPLE_REPORT | 102 | 有 report_id，但当前 SmartBI CLI run 不支持 SIMPLE_REPORT 下载。 |
| no_profile_filters | 51 | profile 没有筛选器信息，取数前需人工确认。 |
| unmatched | 6 | profile 未匹配到 registry report_id。 |
| profile_export_not_pass | 4 | 历史 profile 导出失败，不能自动进入取数。 |

## 投放核心表 Review

| 报表 | report_id | confidence | dry-run | 主要风险 |
|---|---|---:|---|---|
| 投放FB链路指标--素材维度 | I2c9280870195154d154d33720195180019a5150c | 1.0 | yes | has_filter_safety_limits, inspect_workbook_shape_before_analysis, manual_or_default_only_filter |
| 海外投放FB渠道日监控 | I2c928087019c1fbe1fbefe98019c2cefdea27ab9 | 1.0 | yes | inspect_workbook_shape_before_analysis |
| 投放FB链路类型日监控 | I2c928087019d6430643089cc019d7167b0e30c39 | 1.0 | yes | inspect_workbook_shape_before_analysis |
| FB港澳-非港澳测试报表 | I2c928087019581728172bf1e01958a738cf76320 | 1.0 | yes | inspect_workbook_shape_before_analysis |
| 投放全链路目标达成数据-跨月 | I2c928087019635b135b1530d01964f1077197da8 | 1.0 | yes | has_filter_safety_limits, inspect_workbook_shape_before_analysis, manual_or_default_only_filter |

## 发现

| 发现 | 证据 | 置信度 | 反证/缺口 |
|---|---|---|---|
| P0 路由索引可用 | 401/407 profiles 匹配，匹配率 98.53%，核心投放表全部有 report_id | strong | 6 个 profile 未匹配，需要后续清理 |
| 可生成 dry-run 计划，但只限 SPREADSHEET_REPORT | 299 个 SPREADSHEET_REPORT 有 dry-run plan；102 个 SIMPLE_REPORT 无 dry-run plan | strong | SIMPLE_REPORT 后续要走 browser-backed helper 或新 CLI 命令 |
| 筛选器风险必须进入 AI 决策 | 投放FB链路指标--素材维度 16 个筛选器中 1 个 default_only_safe_no_write；全局 137 张表有 filter safety limits | strong | 部分筛选器语义仍 unknown |
| 不能直接自动分析 workbook | 289 张表标记 inspect_workbook_shape_before_analysis | strong | 需要 workbook shape inspect 才能区分 raw table / pivot dashboard |
| 真实投放问题命中已通过初测 | 7 个 smoke query 均返回 report_id 和 confidence=1.0；5 个投放核心表均匹配 | medium | smoke 仍偏少，下一步应扩到 20-30 个业务问题 |

## 结论与建议

| 优先级 | 建议 | 依据 | 风险 | 成功信号 | 护栏/停止条件 |
|---|---|---|---|---|---|
| P0 | 允许进入“AI 找表 + dry-run 计划”应用 | 覆盖率 98.53%，核心投放表命中 | AI 可能把 workbook 当底表 | 所有回答先输出候选表、report_id、风险、dry-run plan | 不允许自动执行 export |
| P0 | 查询结果默认展示筛选器风险 | 137 张表存在 filter safety limits | 默认值造成口径偏差 | 每个候选表都显示 safe/weak/manual | 有 weak/manual 时必须人工确认 |
| P1 | 增加 workbook shape inspect 作为下载后第一步 | 289 张表需 inspect workbook shape | pivot 表被误读 | 导出后先分类 raw_table/pivot_dashboard/unknown | unknown 不进入业务结论 |
| P1 | 为 SIMPLE_REPORT 单独设计只读 probe/export helper | 102 张 SIMPLE_REPORT 有 id 但无 dry-run plan | 当前 CLI run 不支持 | SIMPLE_REPORT 查询返回“可定位但不可 CLI run” | 不用 SPREADSHEET CLI 强行跑 SIMPLE_REPORT |
| P1 | 扩展 eval 问题集 | 当前只有 7 条 smoke | 业务覆盖不足 | 20-30 条投放/BI/续费/学情问题通过 | 命中率低于 80% 先调 scoring，不接自动化 |

## 交付物

- Route index: outputs/bi_catalog_registry/bi_report_route_index_20260520.json
- Join report: outputs/bi_catalog_registry/bi_report_route_join_report_20260520.md
- Smoke tests: outputs/bi_catalog_registry/bi_route_smoke_tests_20260520.md
- Review result: outputs/bi_catalog_registry/bi_route_review_result_20260520.md

## 下一确认闸口

- 是否进入 P1：构造 20-30 条真实业务问题 eval，并把 query_bi_profiles.py 的结果评分做成可回归测试。
- 是否开始设计 SIMPLE_REPORT 的只读 probe/export 边界。
- 是否把这个 route index 作为投放自动化/投放系统demo 的 BI 数据来源层，只读接入。

# BI Route Agent Reference 20260520

## When To Call

先调用 `query_bi_profiles.py` 的场景：

- 用户提出业务问题但未指定 SmartBI 报表。
- 需要判断应查素材维度、渠道维度、区域维度、学员/订单明细还是周报汇总。
- 需要确认候选表是否有 `report_id`，是否能进入 SmartBI CLI dry-run。
- 需要提前暴露字段覆盖、筛选器风险、dashboard/pivot 风险。

不要调用它替代真实分析；它只解决“先去哪张表查”。

## Recommended Command

```bash
python3 scripts/query_bi_profiles.py \
  --registry outputs/bi_catalog_registry/bi_report_route_index_20260520.json \
  --query '<业务问题>' \
  --metric '<关键指标，如 ROI2 或 例子成本>' \
  --limit 5 \
  --json
```

## JSON Fields

- `report_id`: SmartBI catalog resource id；没有它不能生成 SmartBI CLI task。
- `match_confidence`: 当前主要来自 path join；`1.0` 表示 profile path 与 registry path 精确匹配。
- `sample_columns`: profile 抽到的字段样本，只能判断候选覆盖，不能代表完整口径。
- `filter_summary.safe`: 已学习且格式可控的筛选器数量。
- `filter_summary.weak_or_manual`: 只能默认、需要人工值或存在依赖选项风险的筛选器数量。
- `risk_flags`: 路由风险，例如 `inspect_workbook_shape_before_analysis`、`manual_or_default_only_filter`。
- `dry_run_plan`: 可审查的 SmartBI CLI task 草稿；只能 dry-run，不能自动导出。

## Can Enter SmartBI CLI Dry-run

同时满足：

- `report_id` 存在。
- `match_confidence >= 0.8`。
- `dry_run_plan.config_task.report.type == SPREADSHEET_REPORT`。
- 用户问题、时间窗口、区域/渠道/素材筛选口径清楚。
- dry-run 前不需要人工填写 `manual_business_value_required` 筛选器。

## Must Stop And Ask Human

- `report_id` 缺失或 match_type 是 ambiguous。
- `filter_summary.weak_or_manual > 0` 且需要修改这些筛选器。
- 报表是 dashboard/monitor/pivot，用户却要求底表级 join 或归因。
- 业务问题涉及预算调整、停投、写回、发布、自动化执行。
- 需要学员ID、订单ID、广告ID、素材ID等主键拼接，但主键和时间粒度未验证。

## Cannot Auto Join

以下情况只能给候选 join 路径，不能自动拼接：

- 素材维度表和渠道维度表只有日期/渠道近似字段，没有明确共同主键。
- ROI2、平台转化、后端转化的口径来源不同。
- 一个候选是 `SPREADSHEET_REPORT` 或 dashboard/pivot，未做 workbook shape inspection。
- 筛选窗口不一致，例如快照日期、开始日期、结束日期、月度/周度粒度混用。

## Role Boundaries

- 数据分析师：用它找候选表、字段、筛选器风险；分析结论必须等真实导出和质量检查后再给。
- 投放自动化 Agent：只能作为 Read-only Intelligence 的取数路由，不得触发预算、停投、写回。
- 周报 Agent：可用它选择周报候选源和 dry-run task；生成周报前必须检查 workbook shape。
- 技术指挥官：负责把 route index 接到 config draft / dry-run / inspection 链路，不负责业务口径拍板。
- GAO / AI Growth OS：放在 BI/内部数据层，服务投放层和素材层；不升级成新的大系统或自动化实体。

## Current Eval Evidence

- Q1 pass: FB 素材 ROI2 为什么差，应该查哪些表？
- Q2 pass: 台湾渠道例子成本上升，应该查哪些表？
- Q3 pass: 港澳/非港澳 FB 表现拆解，应该查哪些表？
- Q4 pass: 某素材空耗，要查素材维度还是渠道维度？
- Q5 pass: ROI2 和平台转化不一致，应该查哪里？
- Q6 pass: FB 周报整体趋势用哪张表？
- Q7 pass: 素材维度和渠道维度是否有候选 join 路径？
- Q8 weak: 学员/订单级数据在哪些表？
- Q9 pass: 哪些筛选器不能自动改？
- Q10 pass: 哪些报表只能当 dashboard 参考，不能当底表？

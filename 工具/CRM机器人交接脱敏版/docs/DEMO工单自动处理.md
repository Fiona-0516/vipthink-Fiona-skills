# DEMO绿色通道工单自动处理 — 技术文档

## 概述

自动处理DEMO绿色通道工单，实现从领取到排课到关闭的全流程自动化。

## 文件

- `demo_auto_processor.py` — 核心处理器
- `work_order_poller.py` — 定时轮询服务

## 数据流

```
work_order_poller (定时轮询)
  → allWorkOrderList (status=4 待分配)
  → 遍历每条工单
  → demo_auto_processor.auto_process_order(order, token)
    → ① 获取工单详情 (detail?id=xxx)
    → ② 解析 fieldValues
    → ③ 前置检查
      ├─ 信息不完整 → 退出通知人工
      ├─ 国内学员 → 退出（留在待分配）
      └─ 海外学员 → 继续
    → ④ 解析时间/课件/语种
    → ⑤ 查匹配课节 (live/lists)
    → ⑥ 预判断能否处理
      ├─ 不能 → 退出通知人工
      └─ 能 → 继续
    → ⑦ 领取工单 (updateWorkOrderHandler)
       └─ 场景C额外：先创建课节再领取
    → ⑧ 排入学员 (live_student/add)
    → ⑨ 写跟进 (follow/save)
    → ⑩ 关闭工单 (close)
```

## 三种处理场景

### 场景A：无指定老师，查到匹配课节

```
解析工单 → live/lists(不带teacherId) → 找到匹配课节
→ 领取工单 → live_student/add排入 → 跟进 → 关闭
```

### 场景B：有指定老师，查到匹配课节

```
解析工单 → live/lists(带teacherId) → 找到匹配课节
→ 领取工单 → live_student/add排入 → 跟进 → 关闭
```

### 场景C：有指定老师，无匹配课节但可新建

```
解析工单 → live/lists(带teacherId) → 无匹配
→ availableDays → 确认老师可用
→ getChapters → cnId
→ lesson/create → 创建新课节
→ ✅ 创建成功后才领取工单
→ live_student/add排入 → 跟进 → 关闭
```

**⚠️ 场景C修正（2026-05-26）**：原流程是先领取再创建课节，如果创建失败工单会被卡住。修正为**先创建课节成功后再领取**。

## 语种→DEMO课类映射

| 语种 | cateId | 课类名称 |
|------|--------|----------|
| 中文/普通话 | 55 | 数学思维（DEMO） |
| 海外中文 | 4088 | 豌豆益智DEMO（海外中文） |
| 台湾 | 2993 | 豌豆益智DEMO（台湾） |
| 英语/全英 | 1896 | 豌豆益智DEMO（英文） |
| 粤语 | 1894 | 豌豆益智DEMO（粤语） |
| 中英 | 1953 | 豌豆益智DEMO（中英） |

## 国内外判断

```python
# 调用 GET /member/v1/back/ol-user/findDetailById
# userArea.oversea: True=海外, False=国内
# 国内学员留在待分配，不自动处理
# 海外学员排 cateId=4088（海外中文）
```

## 时间解析规则

工单中的意向时间格式多样，需统一处理：

1. `周六-14:00` → 最近一个周六14:00
2. `周六 14:00` → 同上
3. `周六14:00` → 同上
4. 全角冒号 `周六-14：00` → 先转半角再解析
5. **同天判断**：如果今天就是目标星期几且时间未过，则排当天

```python
def calc_next_date_for_weekday(weekday_name, hour, minute):
    """计算下一个目标日期（支持同天判断）"""
    weekday_map = {'一':0,'二':1,'三':2,'四':3,'五':4,'六':5,'日':6}
    target = weekday_map[weekday_name]
    now = datetime.now()
    days_ahead = target - now.weekday()
    
    if days_ahead < 0:
        days_ahead += 7
    elif days_ahead == 0:
        # 同天判断：未过则排当天
        target_time = now.replace(hour=hour, minute=minute)
        if now >= target_time:
            days_ahead = 7
    
    return (now + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
```

## 好老师匹配

`teacher_ratings.json` 中维护老师评级：

```json
{
  "好": [3301, 3302, ...],
  "中1": [...],
  "中2": [...],
  "差": [...]
}
```

排课优先级：地区属性一致 > 好老师优先级，海外学生优先排海外老师。

## 交人工场景

以下情况不领取工单，钉钉通知人工处理：

1. 工单信息不完整（缺学员ID/时间/课件）
2. 无指定老师 + 查不到匹配课节
3. 指定老师 + 时段有其他课（需转移学生）
4. 指定老师 + 老师资源不可用
5. 指定老师 + 新建课节失败

## Bug修复记录

| 日期 | Bug | 修复 |
|------|-----|------|
| 2026-05-26 | 全角冒号"："导致时间解析失败 | `parse_intended_time`中全角→半角 |
| 2026-05-26 | `studentCount`/`maxClassNum`字符串比较导致满班判断错误 | 强制`int()` |
| 2026-05-26 | `relateMe=0`返回错误 | 改为`relateMe=7` |
| 2026-05-26 | 周二排到了周三 | `calc_next_date_for_weekday`增加同天判断 |
| 2026-05-26 | 处理不了还把工单领了 | 场景C先创建课节再领取 |

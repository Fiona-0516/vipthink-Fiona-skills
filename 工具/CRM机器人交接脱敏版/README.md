# CRM 教务助手 — 完整复用手册

> 本文档包含所有代码、API、配置和业务逻辑，上传给 Claude Code 后可直接阅读复现全部功能。
> 最后更新：2026-05-27

---

## 一、系统架构总览

```
                         ┌─────────────────────┐
                         │   CRM 后台 API       │
                         │ ems.vipthink.cn      │
                         │ tqs.vipthink.cn      │
                         │ ticket.vipthink.cn   │
                         └──────────┬──────────┘
                                    │ Bearer Token
                 ┌──────────────────┼──────────────────┐
                 │                  │                  │
                 ▼                  ▼                  ▼
        ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
        │ CRM API 服务  │  │  钉钉机器人   │  │ 企微自建应用  │
        │ (FastAPI)    │  │ (Stream模式) │  │ (回调服务)   │
        │ 端口: 8090   │  │ 无HTTP端口   │  │ 端口: 8091   │
        │              │  │              │  │              │
        │ 统一API网关   │  │ 群内@触发    │  │ AI对话+CRM   │
        │ 查班/锁班/排课 │  │ 查班/锁班/排课│  │ (待域名上线) │
        └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
               │                 │                  │
               └─────────┬───────┘                  │
                         │                          │
                         ▼                          ▼
                ┌────────────────┐        ┌──────────────────┐
                │ crm_query.py   │        │ wecom_ai.py       │
                │ CRM操作核心模块 │        │ AI对话处理         │
                └────────────────┘        └──────────────────┘
```

### 4 个独立服务

| 服务 | 端口 | 入口 | 用途 | 依赖 |
|------|------|------|------|------|
| CRM API 服务 | 8090 | HTTP API | CRM查询/操作的统一HTTP接口 | crm_query.py |
| 钉钉机器人 | 无（长连接） | dingtalk-stream | 群内@机器人触发查班/锁班/排课 | crm_query.py, intent_parser.py |
| 企微回调服务 | 8091 | HTTP回调 | 接收企微自建应用消息，AI对话+CRM操作 | wecom_*.py, crm_query.py |
| 企微客服服务 | 8092 | sync_msg轮询 | 面向外部微信用户的AI客服 | wecom_*.py, wecom_kf_service.py |

---

## 二、源码文件说明

### 2.1 核心模块

| 文件 | 行数 | 职责 |
|------|------|------|
| `crm_query.py` | ~1500 | CRM API调用封装：班级查询、锁班/解锁、排课/移出、Token管理、课程阶段配置 |
| `crm_api_service.py` | ~840 | FastAPI HTTP服务(8090)：统一API接口，API Key鉴权 |
| `bot.py` | ~1600 | 钉钉机器人主程序：dingtalk-stream长连接，意图识别+权限控制+CRM操作 |
| `intent_parser.py` | ~565 | 钉钉消息意图识别：正则匹配+LLM兜底 |
| `query_parser.py` | ~400 | 查班指令解析：课类/阶段/时间/老师名提取 |

### 2.2 工单处理

| 文件 | 行数 | 职责 |
|------|------|------|
| `demo_auto_processor.py` | ~1000 | DEMO绿色通道工单自动处理：领取→解析→排课→跟进→关闭 |
| `work_order_poller.py` | ~600 | 工单轮询服务：定时扫描待分配工单，调用auto_processor处理 |

### 2.3 企微模块

| 文件 | 行数 | 职责 |
|------|------|------|
| `wecom_callback_service.py` | ~272 | 企微回调主服务(FastAPI)：消息接收/验证/路由 |
| `wecom_crypto.py` | ~261 | 企微消息加解密：AES-CBC，签名验证 |
| `wecom_token.py` | ~154 | 企微Access Token管理：获取+缓存+自动刷新 |
| `wecom_sender.py` | ~186 | 企微消息发送：文本/Markdown/卡片 |
| `wecom_ai.py` | ~623 | AI对话处理：OpenAI兼容API，对话历史管理 |
| `wecom_kf_service.py` | ~1059 | 企微客服服务：sync_msg轮询，身份验证，排课操作 |

### 2.4 辅助模块

| 文件 | 行数 | 职责 |
|------|------|------|
| `update_token.py` | ~250 | CRM Token更新脚本：支持多种格式，CST/TCT校验，API验证 |
| `auto_refresh_token.py` | ~82 | 浏览器自动刷新Token（配合云电脑agent-browser） |
| `notify.py` | ~129 | 通知模块：钉钉消息发送 |
| `dingtalk_send.py` | ~113 | 钉钉webhook发送工具 |
| `crm_browser.py` | ~100 | CRM浏览器自动化（旧版，已被agent-browser替代） |
| `health_monitor.sh` | ~50 | crontab健康监控脚本 |

---

## 三、CRM API 完整文档

### 3.1 API网关

系统有3套API网关，**Bearer Token通用**（EMS获取的Token可跨网关使用）：

| 网关 | Base URL | 用途 |
|------|----------|------|
| EMS | `https://ems.vipthink.cn/gateway/route__jw/api/` | 班级管理、学员管理、排课操作 |
| TQS | `https://tqs.vipthink.cn/api/` | 课表管理、新增排课 |
| Ticket | `https://ticket.vipthink.cn` | 工单系统 |

### 3.2 认证

```
Authorization: Bearer eyJhbGciOiJzaGEyNTYiLCJ0eXAiOiJKV1QifQ...
```

- Token 来源：CRM登录后 `localStorage.getItem('TOKEN_KEY')` → `.Authorization`
- ⚠️ **不要用** `CRM_TOKEN_KEY`（那是工单系统旧版token，API返回"非法员工令牌"）
- Token 类型必须是 **CST**（payload中 `tza=CST`），TCT类型无效
- Token 有效期约13小时，需每日刷新

### 3.3 EMS API 接口

#### 班级查询
```
POST /classs/manage
Body: {"classStuType":0, "isMax":1, "pageNo":1, "pageSize":50, "cateSids":[3282], "lanId":63}
```
- `cateSids`: 课程阶段ID数组（见3.5映射表）
- `lanId`: 语种ID（90=普通话, 63=英语, 91=中英, 69=粤语）
- `isMax`: 0=不含满班, 1=含满班
- 响应: `{code:200, data:{list:[...]}}`

#### 锁班/解锁
```
POST /grades_v2/edit
Body: {"classId":81846, "maxClassNum":6, "weekCycle":2, "catePid":3243, "cateSid":3282, "isInsertable":0}
```
- `isInsertable`: 0=不允许插班(锁班), 1=允许插班(解锁)

#### 允许/禁止补课
```
POST /grades_v2/edit
Body: {"classId":81846, "maxClassNum":6, "weekCycle":2, "catePid":3243, "cateSid":3282, "isMakeupLive":1}
```
- `isMakeupLive`: 1=允许补课, 2=禁止补课

#### 排课（学员加入课节）
```
POST /live_student/add
Body: {"userId":28541306, "liveId":17017724}
```

#### 移出学员
```
POST /grade_student/del
Body: {"userId":28541306, "classId":81846, "liveIds":[17017724]}
```

#### 排课预览（验证学员是否可加入）
```
POST /live_student/validateLiveStudent
Body: {"liveId":17017724, "userId":28541306}
```

#### 获取班级课节列表
```
POST /classs/getLiveList
Body: {"classId":81846, "liveStatus":0}
```
- `liveStatus`: 0=全部, 1=待上课, 2=已下课

#### 获取学员课时
```
POST /user_hour/getUserHour
Body: {"userId":28541306, "subject":0}
```

#### 搜索学员
```
POST /student/getStudent
Body: {"keyword":"28541306"}
```

#### 班级详情
```
POST /classs/detail
Body: {"classId":81846}
```

#### 课节列表查询（DEMO试听课排课核心）
```
POST /live/lists
Body: {"courseType":2, "liveStatus":0, "cateId":55, "stepId":3282, "teacherId":3301}
```
- `courseType`: 1=普通课, 2=试听课(DEMO), 6=补课
- `cateId`: 课类ID（DEMO映射见3.6）

### 3.4 TQS API 接口

#### 新增排课
```
POST https://tqs.vipthink.cn/api/education/lesson/create
Body: {
  "size":4, "cateId":55, "stepId":3282, "cnId":12345,
  "consumeHour":1, "courseType":2, "duration":40,
  "startTime":"2026-05-27 20:10:00", "teacherId":3301
}
```
- `size`: 课节容量（一般4或8）
- `cnId`: 课件ID（通过 getChapters 获取）
- `consumeHour`: 消耗课时
- `duration`: 课节时长（分钟）

#### 获取课件
```
POST https://tqs.vipthink.cn/api/education/course/getChapters
Body: {"cateId":55, "stepId":3282}
```

#### 可排课日期
```
POST https://tqs.vipthink.cn/api/education/demo_resource/availableDays
Body: {"cateId":55, "stepId":3282}
```

### 3.5 Ticket API 接口（工单系统）

认证：**CRM Bearer Token 通用**

#### 工单列表
```
POST /v-ticket/work-order/allWorkOrderList
Body: {"workOrderTypeId":1, "status":4, "relateMe":7, "pageNo":1, "pageSize":20}
```
- `workOrderTypeId`: 1=DEMO绿色通道
- `status`: 4=待分配
- `relateMe`: **必须用1或7**（0和8会返回错误）
- ⚠️ 列表接口的 `fieldValues` 为 null，需调详情接口获取

#### 工单详情
```
GET /v-ticket/work-order/detail?id=2568390
```
返回 `fieldValues` 数组，包含：
- fieldId 274: 学员ID
- fieldId 275: 意向时间
- fieldId 276: 备选时间
- fieldId 277: 原因
- fieldId 278: 意向课件
- fieldId 286: 是否接受同阶其他课件
- fieldId 287: 特殊诉求
- fieldId 1005: 特殊语种选择

#### 领取工单
```
POST /v-ticket/work-order/updateWorkOrderHandler
Body: {"workOrderIdList":[2568390], "handlerList":[3301], "type":1}
```

#### 写跟进记录
```
POST /v-ticket/work-order-follow/save
Body: {"workOrderId":2568390, "content":"已排入课节xxx", "followType":1}
```
- ⚠️ 必须先领取工单成为处理人才能写跟进

#### 关闭工单
```
POST /v-ticket/work-order/close
Body: {"workOrderId":2568390}
```

### 3.5 课类×阶段×语种映射

#### 豌豆明思2025课类结构

| 课类名称 | catePid | 覆盖阶段 | 支持语种 |
|----------|---------|----------|----------|
| 豌豆明思2025（无后缀） | 3243 | S1-S9 | 普通话(90)、英语(63)、中英(91)、粤语(69) |
| 豌豆明思2025（英语） | 3202 | S1-S7 | 英语(63)、中英(91) |
| 豌豆明思2025（粤语） | 3203 | S1-S7 | 粤语(69)、普通话(90) |
| 豌豆明思2025（台湾） | 4043 | S1-S6 | 普通话(90) |

#### 语种ID映射

| 语种 | lanId | 备注 |
|------|-------|------|
| 普通话 | 90 | 台湾用户通用 |
| 英语/全英 | 63 | |
| 中英/中文 | 91 | |
| 粤语 | 69 | |

#### 课程阶段ID（cateSid）

| 阶段 | 英语(3202) | 粤语(3203) | 台湾(4043) | 无后缀(3243) |
|------|-----------|-----------|-----------|-------------|
| S1 | 3282 | 3275 | 4074 | 3269 |
| S2 | 3283 | 3276 | 4075 | 3260 |
| S3 | 3284 | 3277 | 4076 | 3261 |
| S4 | 3285 | 3278 | 4077 | 3262 |
| S5 | 3286 | 3279 | 4078 | 3263 |
| S6 | 3287 | 3280 | 4044 | 3264 |
| S7 | 3288 | 3281 | - | 3265 |
| S8 | - | - | - | 3266 |
| S9 | - | - | - | 3267 |

#### 查询规则

1. **普通话**: 走无后缀课类(3243) + lanId=90
2. **台湾用户**: S1-S6走台湾课类(4043)，S7走粤语课类(3203)+lanId=90
3. **英语/粤语**: 对应有后缀课类，或无后缀课类+对应lanId
4. **中英**: 分布在3个课类（中英专属+英语课类+无后缀课类），查询时需合并并按classId去重

### 3.6 DEMO课类映射（新增排课用）

| 课类名称 | cateId |
|----------|--------|
| 数学思维（DEMO） | 55 |
| 豌豆益智DEMO（海外中文） | 4088 |
| 豌豆益智DEMO（台湾） | 2993 |
| 豌豆益智DEMO（英文） | 1896 |
| 豌豆益智DEMO（粤语） | 1894 |
| 豌豆益智DEMO（中英） | 1953 |

---

## 四、钉钉机器人

### 4.1 运行模式

使用 **dingtalk-stream** 长连接模式，无需公网回调地址。

### 4.2 凭证

| 配置项 | 值 | 说明 |
|--------|-----|------|
| CLIENT_ID | `<DINGTALK_CLIENT_ID>` | 钉钉应用 AppKey |
| CLIENT_SECRET | `<DINGTALK_CLIENT_SECRET>` | 钉钉应用 AppSecret |
| 机器人名称 | 教务小助手 | 群内@触发 |

### 4.3 支持指令

| 指令 | 示例 | 权限 |
|------|------|------|
| 查班 | `台湾S3 查班` / `Level3 英语 周六14:00 查班` | 所有人 |
| 锁定班级 | `锁定 81846` | 管理员/授权用户 |
| 解锁班级 | `解锁 81846` | 管理员/授权用户 |
| 按老师批量解锁 | `解锁 Rovie` | 管理员/授权用户 |
| 按老师批量锁班 | `上锁 Rovie` | 管理员/授权用户 |
| 允许补课 | `允许补课 81846` | 管理员/授权用户 |
| 禁止补课 | `禁止补课 81846` | 管理员/授权用户 |
| 排课预览 | `排课预览 81846 28541306` | 管理员 |
| 执行排课 | `排课 81846 28541306` | 管理员 |
| 移出学员 | `移出 81846 28541306` | 管理员 |
| 查看Token | `查看Token` | 管理员 |
| 更新Token | `更新Token Bearer xxx` | 管理员 |
| 设置管理员 | `设置管理员 @用户` | 管理员 |
| 设置用户权限 | `设置用户权限 群ID 工号 昵称 权限列表` | 管理员 |

### 4.4 权限体系

**全部权限类型**: query, lock_class, unlock_class, allow_makeup, disallow_makeup, allow_transfer, disallow_transfer, preview_schedule, schedule

- **管理员**（`admin_list.json`）：拥有所有权限
- **群权限**（`permission_config.json`）：可按群/按用户配置允许的操作
- **默认**：所有群可查询，其他操作需授权

### 4.5 意图识别流程

```
用户消息
  → intent_parser.py 正则匹配
    → 命中 → 直接返回意图+参数
    → 未命中 → LLM兜底（调用OpenAI兼容API）
  → 权限检查（permission_config.json）
  → 执行操作（crm_query.py）
  → 格式化返回结果
```

---

## 五、企微机器人

### 5.1 自建应用凭证

| 配置项 | 值 |
|--------|-----|
| CorpID | `<WECOM_CORP_ID>` |
| AgentId | `1000009` |
| Secret | `8Nt-tUeXYEmaqN_8LmkoIo6omIFfe3OTtPK62BPyQk` |
| 回调Token | `<WECOM_CALLBACK_TOKEN>` |
| EncodingAESKey | `<WECOM_ENCODING_AES_KEY>` |
| 回调URL | `https://wecom.vipthink.cn/wecom/callback` |

### 5.2 回调服务流程

```
企微消息
  → GET /wecom/callback（验证URL有效性，echostr解密回传）
  → POST /wecom/callback（接收消息）
    → 签名验证（msg_signature）
    → XML解析 → AES解密 → 获取消息内容
    → wecom_ai.py 处理（AI对话/CRM操作）
    → wecom_sender.py 回复
```

### 5.3 智能体配置（企微侧）

企微智能体通过「工具」插件调用CRM API：

```
用户在企微对话
  → 企微智能体解析意图
  → 调用插件（URL指向CRM API服务的/api/command）
  → CRM API执行操作并返回结果
  → 智能体整理回复用户
```

插件配置要点：
- URL: `http://CRM_API地址/api/command`
- 请求方式: POST
- 参数全走Body，类型为String（企微插件不支持GET QueryString和int类型）
- Header: `X-API-Key: <CRM_API_KEY>`

### 5.4 上线前提

企微回调服务需要**备案域名**：

1. IT部门在 `vipthink.cn` 下新增DNS记录: `wecom → 服务器公网IP`
2. Nginx配置443端口 + SSL证书
3. 企微后台配置接收消息URL: `https://wecom.vipthink.cn/wecom/callback`

---

## 六、工单自动处理

### 6.1 总流程

```
轮询待分配工单(status=4)
  → 解析 fieldValues（学员ID/时间/课件/语种/指定老师）
  → 预判断：能否自动处理？
    ├─ ❌ 不能 → 不领取，钉钉通知人工
    └─ ✅ 能 → 领取工单 → 分场景处理 → 跟进 → 关闭
```

### 6.2 三种自动处理场景

| 场景 | 条件 | 处理链路 |
|------|------|----------|
| A | 无指定老师，查到匹配课节 | 领取→live/lists查课→排入学员→跟进→关闭 |
| B | 有指定老师，查到匹配课节 | 领取→live/lists(带teacherId)查课→排入学员→跟进→关闭 |
| C | 有指定老师，无匹配课节但可新建 | 领取→availableDays→lesson/create→排入学员→跟进→关闭 |

### 6.3 预判断逻辑（领取前执行，关键原则！）

```
解析工单字段
  ├─ 工单信息不完整？→ ❌ 不领取，通知人工
  ├─ 无指定老师
  │    ├─ 查到匹配课节 → ✅ 领取，场景A
  │    └─ 查不到匹配课节 → ❌ 不领取，通知人工
  └─ 有指定老师
       ├─ 查到匹配课节 → ✅ 领取，场景B
       ├─ 无匹配课节，老师该时段可用 → ✅ 领取，场景C
       └─ 无匹配课节，老师不可用/有冲突 → ❌ 不领取，通知人工
```

**⚠️ 场景C流程修正（2026-05-26）**：先创建课节成功后再领取工单，避免创建失败但工单已被领取卡住。

### 6.4 单条工单完整API调用链

```
① POST allWorkOrderList          → 拿到工单列表
② GET  detail?id=xxx             → 拿fieldValues（列表接口fieldValues为null）
③ POST updateWorkOrderHandler    → 领取工单（type=1, handlerList=[UID]）
④ POST live/lists                → 查试听课节（courseType=2, liveStatus=0）
   └─ 场景C额外：
      POST availableDays         → 查老师可用日期
      POST getChapters           → 课件名→cnId
      POST lesson/create         → 新建课节
⑤ POST live_student/add          → 排入学员
⑥ POST follow/save               → 写跟进记录
⑦ POST close                     → 关闭工单
```

### 6.5 关键业务规则

1. **国内外分流**: 海外学员工单才走自动处理，国内工单留在待分配
2. **语种→DEMO课类映射**: 中文→55, 海外中文→4088, 台湾→2993, 英语→1896, 粤语→1894, 中英→1953
3. **意向时间解析**: `周六-14:00` → 最近一个周六14:00（支持同天判断：未过则排当天）
4. **好老师匹配**: 排课时优先匹配好老师名单（`teacher_ratings.json`），海外学生优先排海外老师
5. **全角冒号修复**: 工单中的全角冒号"："需自动转半角":"

### 6.6 交人工场景（不领取工单）

| 场景 | 原因 |
|------|------|
| 无指定老师 + 查不到匹配课节 | 无法确定用哪个老师新建 |
| 指定老师 + 时段有其他课 | 转课操作复杂，需人工判断 |
| 指定老师 + 老师资源不可用 | 需协调排班 |
| 指定老师 + 新建课节失败 | 可能老师没开放资源 |
| 工单信息不完整 | 无法自动处理 |

---

## 七、CRM Token 管理

### 7.1 Token获取

登录 `https://crm.vipthink.cn`，从浏览器获取：

```javascript
// ✅ 正确：从 TOKEN_KEY 提取
let tokenData = JSON.parse(localStorage.getItem('TOKEN_KEY'));
let apiToken = tokenData.Authorization;  // "Bearer eyJ..."

// ❌ 错误：CRM_TOKEN_KEY 是旧版工单token，API不认
```

### 7.2 Token验证

```python
# 必须用API调用验证，JWT格式正确不代表有效
import requests, json
with open('crm_token.json') as f:
    token = json.load(f)['token']
headers = {"authorization": f"Bearer {token}", "content-type": "application/json"}
resp = requests.post("https://ems.vipthink.cn/gateway/route__jw/api/classs/manage",
    headers=headers, json={"classStuType":0,"isMax":1,"pageNo":1,"pageSize":1})
# code=200 才算成功，code=201="非法员工令牌"
```

### 7.3 自动刷新

- 定时日程（每日凌晨4点）触发
- 浏览器自动化登录CRM → 提取Token → 更新crm_token.json → API验证
- Token有效期约13小时

---

## 八、部署指南

### 8.1 环境要求

- Ubuntu 20.04+ / CentOS 7+
- Python 3.10+
- 2核4G100G 足够运行全部4个服务

### 8.2 依赖安装

```bash
pip3 install dingtalk-stream==0.24.3 fastapi==0.135.1 uvicorn==0.42.0 \
  httpx==0.27.0 requests==2.32.5 pycryptodome==3.23.0 pydantic==2.12.5 Pillow==12.1.1
```

### 8.3 路径替换

部署时需将代码中的路径替换为实际安装路径：

```bash
sed -i 's|/app/data/所有对话/主对话/dingtalk_stream_bot|/opt/crm-bot|g' \
  bot.py crm_api_service.py wecom_callback_service.py wecom_kf_service.py \
  auto_refresh_token.py update_token.py *.service start*.sh
```

### 8.4 启动顺序

```bash
# 1. CRM API 服务（其他服务依赖）
systemctl start crm-api

# 2. 钉钉机器人
./start.sh start

# 3. 企微回调（需域名）
systemctl start wecom-callback

# 4. 企微客服（需配置open_kfid）
systemctl start wecom-kf
```

### 8.5 健康检查

```bash
curl http://localhost:8090/api/health   # CRM API
curl http://localhost:8091/health        # 企微回调
curl http://localhost:8092/health        # 企微客服
./start.sh status                        # 钉钉机器人
```

---

## 九、已知坑与注意事项

### 9.1 CRM API 坑

1. **两个Token Key**: `TOKEN_KEY`(API用) vs `CRM_TOKEN_KEY`(工单旧版token)，API只认前者
2. **CST vs TCT**: JWT payload中 `tza=CST` 有效，`tz=TCT` 无效
3. **JWT格式正确≠有效**: 必须用API调用验证
4. **classs/manage不返回满班**: 查满班需要 `isMax=1`
5. **relateMe参数**: 工单列表查询必须用1或7，不能用0（返回错误）

### 9.2 企微坑

1. **备案域名**: 企微回调URL必须用备案域名，不能用IP或免费隧道
2. **参数全走Body**: 企微智能体插件不支持GET QueryString和int类型
3. **Secret可能变更**: 企微后台重新生成Secret后旧Token立即失效

### 9.3 工单坑

1. **fieldValues在列表接口为null**: 必须调详情接口
2. **退回按钮不存在**: 工单详情页可能没有退回/转派按钮（权限问题），领取前务必确认能处理
3. **全角冒号**: 工单中的时间可能用全角冒号"："，需转半角
4. **场景C先创建再领取**: 避免创建课节失败但工单已被领取

### 9.4 钉钉坑

1. **繁体字**: 台湾课节可能用"週"而非"周"，需统一处理
2. **中英班多课类**: 中英班分布在3个课类，查询需合并并按classId去重
3. **前导零**: 时间匹配需normalize（"9:00"和"09:00"视为相同）

---

## 十、Nginx 配置参考

```nginx
server {
    listen 8888;
    server_name _;

    # CRM API
    location /api/ {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120s;
    }

    # 企微回调
    location /wecom/ {
        proxy_pass http://127.0.0.1:8091;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120s;
    }
}
```

---

## 十一、架构决策记录

| 决策 | 原因 |
|------|------|
| 钉钉用Stream模式 | 无需公网回调地址，更稳定 |
| CRM API独立服务 | 解耦，多端复用，统一鉴权 |
| 万能接口 /api/command | 企微智能体一个插件只能配一个URL |
| 企微参数全走Body+String | 企微插件不支持GET QueryString和int |
| 企微客服用sync_msg轮询 | 域名备案阻塞回调方案 |
| 权限配置用JSON文件 | 简单轻量，适合当前规模 |
| 场景C先创建再领取 | 避免创建失败工单卡住 |
| 满班查询需isMax=1 | CRM默认不返回满班数据 |

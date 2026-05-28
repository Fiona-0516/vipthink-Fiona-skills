# CRM API 接口速查

## API网关

| 网关 | Base URL | 用途 |
|------|----------|------|
| EMS | `https://ems.vipthink.cn/gateway/route__jw/api/` | 班级/学员/排课 |
| TQS | `https://tqs.vipthink.cn/api/` | 课表/新增排课 |
| Ticket | `https://ticket.vipthink.cn` | 工单系统 |

**认证**: Bearer Token（三网关通用），Token从CRM的`localStorage.TOKEN_KEY.Authorization`获取

---

## EMS 接口

### 班级管理

| 接口 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/classs/manage` | POST | `cateSids,lanId,isMax,pageNo,pageSize,classStuType` | 班级查询 |
| `/classs/detail` | POST | `classId` | 班级详情 |
| `/classs/getLiveList` | POST | `classId,liveStatus` | 班级课节列表 |
| `/grades_v2/edit` | POST | `classId,maxClassNum,weekCycle,catePid,cateSid,isInsertable,isMakeupLive` | 班级编辑(锁班/补课) |

### 学员操作

| 接口 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/live_student/add` | POST | `userId,liveId` | 排课(学员加入课节) |
| `/grade_student/del` | POST | `userId,classId,liveIds` | 移出学员 |
| `/live_student/validateLiveStudent` | POST | `liveId,userId` | 排课预览(验证可否加入) |
| `/grade_student/joinlives` | POST | `userId,classId,liveIds` | 批量加入课节 |
| `/student/getStudent` | POST | `keyword` | 搜索学员 |
| `/user_hour/getUserHour` | POST | `userId,subject` | 学员课时 |

### 课节查询

| 接口 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/live/lists` | POST | `courseType,liveStatus,cateId,stepId,teacherId` | 课节列表(DEMO排课核心) |

### 枚举值

- courseType: 1=普通课, 2=试听课, 6=补课
- liveStatus: 0=全部, 1=待上课, 2=已下课, 3=取消
- isInsertable: 0=锁班, 1=解锁
- isMakeupLive: 1=允许补课, 2=禁止补课

---

## TQS 接口

| 接口 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/education/lesson/create` | POST | `size,cateId,stepId,cnId,consumeHour,courseType,duration,startTime,teacherId` | 新增排课 |
| `/education/course/getChapters` | POST | `cateId,stepId` | 获取课件列表 |
| `/education/demo_resource/availableDays` | POST | `cateId,stepId` | 可排课日期 |

---

## Ticket 接口

| 接口 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/v-ticket/work-order/allWorkOrderList` | POST | `workOrderTypeId,status,relateMe,pageNo,pageSize` | 工单列表 |
| `/v-ticket/work-order/detail` | GET | `id` | 工单详情(含fieldValues) |
| `/v-ticket/work-order/updateWorkOrderHandler` | POST | `workOrderIdList,handlerList,type=1` | 领取工单 |
| `/v-ticket/work-order-follow/save` | POST | `workOrderId,content,followType` | 写跟进 |
| `/v-ticket/work-order/close` | POST | `workOrderId` | 关闭工单 |

### 工单 fieldValues fieldId

| fieldId | 含义 |
|---------|------|
| 274 | 学员ID |
| 275 | 意向时间 |
| 276 | 备选时间 |
| 277 | 原因 |
| 278 | 意向课件 |
| 286 | 是否接受同阶其他课件 |
| 287 | 特殊诉求 |
| 1005 | 特殊语种选择 |

---

## 通用响应格式

```json
{
  "code": 200,     // EMS: 200=成功, 201=失败; Ticket: 0=成功
  "msg": "success",
  "data": {}
}
```

## 错误码

| code | 含义 |
|------|------|
| 200 | EMS成功 |
| 201 | EMS失败（"非法员工令牌"=Token类型错误） |
| 0 | Ticket成功 |
| 1000001 | "网络异常"（Token无效或参数错误） |
| 1000073 | "非法员工令牌"（Token类型错误） |

- [认证方式](#认证方式)
- [API 端点](#api-端点)

---

## 🔍 概述

**服务地址**: `http://lacedore.org:6789`

## 🔐 认证方式

### 认证方式

所有用户端点都需要在请求头中携带 API 密钥：


```
X-API-Key: sk-YOUR-API-KEY
```

### 端点列表

| 方法 | 端点 | 功能 | 消耗积分 |
|------|------|------|----------|
| `GET` | `/quota` | 查询剩余积分 |
| `GET` | `/upstream/status` | 检测上游服务状态 |
| `POST` | `/redeem` | 兑换卡密增加积分 |
| `POST` | `/verify` | 创建验证任务（返回 task_id）| ✅ 成功时扣 1 |
| `GET` | `/verify/status/{task_id}` | 查询验证任务状态 |
| `POST` | `/verify/batch` | 批量验证 | ✅ 每成功一个扣 1 |
| `POST` | `/cancel` | 取消验证 |

### 端点详情

#### `GET /quota` - 查询剩余积分
**请求参数**: 无

**返回示例**:
```json
{
  "api_key": "sk-XXXX-XXXX-XXXX-XXXX",
  "credits": 100
}
```

#### `GET /upstream/status` - 检测上游服务状态
**说明**: 用于检测后端连接的上游服务是否可用，不消耗积分。

**请求参数**: 无

**返回示例（上游可用）**:
```json
{
  "available": true,
  "status_code": 200,
  "latency_ms": 123
}
```

**返回示例（上游不可用 / 超时）**:
```json
{
  "available": false,
  "latency_ms": 30000,
  "error": "Connection timeout or network error"
}
```

#### `POST /redeem` - 兑换卡密
**请求参数**:
```json
{
  "code": "XXXX-XXXX-XXXX"
}
```

**返回示例**:
```json
{
  "message": "Successfully redeemed 50 credits",
  "code": "XXXX-XXXX-XXXX",
  "credits_added": 50,
  "credits_total": 150,
  "api_key": "sk-XXXX-XXXX-XXXX-XXXX"
}
```

#### `POST /verify` - 创建验证任务（异步）
**说明**: 提交验证请求后立即返回 task_id，然后在后台处理验证

**请求参数**:
```json
{
  "verification_id": "67e4a1234567890abcdef123"
}
```

**返回示例**:
```json
{
  "task_id": "xYz123AbC456",
  "status": "pending",
  "message": "Verification task created. Use GET /verify/status/{task_id} to check progress."
}
```

#### `GET /verify/status/{task_id}` - 查询验证任务状态
**说明**: 使用 task_id 查询验证任务的当前状态

**返回示例** (处理中):
```json
{
  "task_id": "xYz123AbC456",
  "status": "processing",
  "api_key": "sk-XXXX-XXXX-XXXX-XXXX",
  "verification_id": "67e4a1234567890abcdef123",
  "currentStep": "pending",
  "message": "Processing...",
  "created": "2024-01-01T12:00:00Z"
}
```

**返回示例** (已完成):
```json
{
  "task_id": "xYz123AbC456",
  "status": "completed",
  "api_key": "sk-XXXX-XXXX-XXXX-XXXX",
  "verification_id": "67e4a1234567890abcdef123",
  "currentStep": "success",
  "message": "Verification successful",
  "success": true,
  "redeemUrl": "https://one.google.com/ai?...",
  "created": "2024-01-01T12:00:00Z"
}
```

**状态说明**:
- `pending`: 任务已创建，等待处理
- `processing`: 正在处理中
- `polling`: 轮询验证状态
- `completed`: 已完成（检查 `success` 字段确认是否成功）
- `error`: 发生错误（查看 `error` 字段了解详情）

#### `POST /verify/batch` - 批量验证
**说明**: 并发处理多个验证请求

**请求参数**:
```json
{
  "verification_ids": [
    "67e4a1234567890abcdef123",
    "67e4a1234567890abcdef124",
    "gen"
  ]
}
```

**返回示例**:
```json
{
  "total": 3,
  "success_count": 2,
  "failed_count": 1,
  "credits_deducted": 2,
  "results": [
    {
      "verificationId": "67e4a1234567890abcdef123",
      "masked": "67e4****ef123",
      "currentStep": "success",
      "message": "Verification successful",
      "success": true,
      "redeemUrl": "https://one.google.com/ai?..."
    },
    ...
  ]
}
```

#### `POST /cancel` - 取消验证
**请求参数**:
```json
{
  "verification_id": "67e4a1234567890abcdef123"
}
```

**返回示例**:
```json
{
  "verificationId": "67e4a1234567890abcdef123",
  "alreadyCancelled": false,
  "currentStep": "cancelled",
  "message": "Verification cancelled"
}
```


## 📝 注意事项

1. **积分消耗**:
   - 每次成功验证消耗 **1 个积分**
   - 失败或取消的验证不消耗积分
   - **积分降为 0 时 API key 不会被删除**，可通过兑换卡密继续使用
   - 批量验证只扣除成功的次数

2. **异步验证流程**:
   - 提交验证后立即返回 task_id
   - 使用 task_id 轮询查询验证状态

3. **卡密使用**:
   - 每个卡密只能兑换一次
   - 已兑换的卡密无法重复使用
   - 卡密不区分大小写

4. **服务连接**:
   - 默认服务地址: `http://lacedore.org:6789`
   - API 文档: `http://lacedore.org:6789/docs`

---
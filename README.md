# Reliable HTTP Notification Service

一个面向内部业务系统的可靠 HTTP 通知投递服务。业务系统只提交“通知意图”，本服务负责持久化、异步投递、失败重试和最终失败记录。

这份作业的重点不是堆功能，而是展示工程判断：边界清楚、可靠性语义诚实、复杂度可控、未来能演进。

## 1. 问题理解

企业内部多个业务系统会在关键事件发生后通知外部供应商 API，例如广告系统、CRM、库存系统。供应商 API 的 URL、Header、Body 都不同，但业务系统并不需要同步读取供应商返回值。

所以核心问题不是“写一个 HTTP 转发器”，而是：

> 如何让业务系统快速、可靠地提交通知意图，并把外部系统的不稳定隔离在业务主链路之外。

## 2. 核心设计

```text
Business System
   |
   | POST /notifications
   v
FastAPI API
   |
   | validate + persist first
   v
SQLite notifications / attempts
   |
   | claim due jobs
   v
Worker + Dispatcher
   |
   | HTTP request with timeout
   v
External Vendor API
```

关键决策：**先落库，再异步投递**。

同步调用外部供应商是坏边界。供应商慢、超时、故障时，内部注册、支付、下单链路都被拖住。这里选择把通知请求持久化后立即返回 `202 Accepted`，后续由 worker 投递。

## 3. 系统边界

### 解决的问题

- 接收内部系统提交的 HTTP 通知任务。
- 支持不同 URL、HTTP method、headers、JSON body。
- 任务持久化，避免进程崩溃后丢通知。
- 异步投递，隔离外部供应商延迟。
- 失败重试，支持指数退避和最大重试次数。
- 记录每次投递 attempt，便于排障。
- worker 崩溃后恢复卡在 `processing` 的任务。
- 提供状态查询接口。

### 明确不解决的问题

- 不做供应商业务适配。CRM 状态、库存逻辑不是本服务职责。
- 不承诺 exactly once。HTTP 超时后无法知道对方是否已处理。
- 不做管理后台。API 和 attempt 记录足够说明第一版核心能力。
- 不做复杂模板 DSL。调用方直接提交最终 URL/Header/Body。
- 不默认引入 Kafka/RabbitMQ。第一版没有证据需要外部队列。
- 不做多租户权限体系。真实环境可由网关或内部认证层补上。


## 3.1 架构边界答辩版

这个系统不是“大而全集成平台”，它的边界是**可靠 HTTP 通知投递**。

它负责：

- 接收通知意图；
- 持久化任务；
- 异步投递 HTTP；
- 失败重试；
- 记录 attempt；
- 暴露状态查询；
- 恢复卡在 `processing` 的任务。

它不负责：

- 产生业务事件；
- 理解 CRM、广告、库存等供应商业务语义；
- 单方面保证 exactly-once；
- 替接收方实现幂等；
- 一开始就拥有完整监控平台或 MQ 平台。

这不是偷懒，是边界设计。系统如果同时负责业务语义、供应商适配、通知投递、监控告警和消息平台，会变成一个无法在第一版讲清楚的泥球。

详细边界见 `docs/system-boundary.md`。

## 4. 投递语义

本服务选择：**at-least-once delivery，至少一次投递**。

原因很现实：HTTP 请求超时时，可能是对方没收到，也可能是对方处理成功但响应丢了。系统如果重试，就可能重复投递。因此 exactly once 在这里是伪命题，除非双方共享事务边界或接收方支持强幂等。

本服务支持 `idempotency_key`，建议调用方传入业务事件唯一标识，例如：

```text
user_registered:u_123
order_paid:o_456
inventory_changed:sku_789:event_001
```

面试时可以直接说：

> 我不承诺 HTTP exactly once，因为那是假的。我承诺至少一次，并把幂等键作为跨系统协作合同。

## 5. 失败处理策略

| 情况 | 处理 |
|---|---|
| 2xx | 标记 `succeeded` |
| 408 / 409 / 425 / 429 | 视为瞬时失败，重试 |
| 5xx | 视为供应商临时故障，重试 |
| 网络异常 / timeout | 重试 |
| 大多数 4xx | 请求本身有问题，不重试，标记 `failed` |
| 达到最大次数 | 标记 `failed` |

退避策略：

```text
base_delay_seconds * 2^(attempt_count - 1)
最大不超过 max_delay_seconds
```

默认值：

```text
max_attempts = 5
base_delay_seconds = 60
max_delay_seconds = 3600
```

## 6. 数据模型

### notifications

保存通知任务的当前状态：

- `id`
- `target_url`
- `method`
- `headers_json`
- `body_json`
- `idempotency_key`
- `status`: `pending` / `processing` / `succeeded` / `retrying` / `failed`
- `attempt_count`
- `max_attempts`
- `next_attempt_at`
- `processing_started_at`
- `last_status_code`
- `last_error`
- `created_at`
- `updated_at`

### notification_attempts

保存每次投递证据：

- `notification_id`
- `attempt_no`
- `status_code`
- `error`
- `duration_ms`
- `created_at`

## 7. API 示例

### 创建通知

```http
POST /notifications
Content-Type: application/json
```

```json
{
  "target_url": "https://vendor.example.com/webhook",
  "method": "POST",
  "headers": {
    "Authorization": "Bearer token",
    "Content-Type": "application/json"
  },
  "body": {
    "event": "user_registered",
    "user_id": "u_123"
  },
  "idempotency_key": "user_registered:u_123",
  "max_attempts": 5
}
```

响应：

```http
202 Accepted
```

```json
{
  "id": "notification-id",
  "status": "pending"
}
```

### 查询状态

```http
GET /notifications/{id}
```

返回当前状态和 attempts。

## 8. 本地运行

安装依赖：

```bash
python -m pip install -r requirements.txt
```

启动 API：

```bash
python -m uvicorn src.app.main:app --reload
```

另开一个终端启动常驻 worker：

```bash
python -m src.app.worker_runner
```

worker 支持参数覆盖：

```bash
python -m src.app.worker_runner --poll-interval 1 --batch-size 10 --timeout 5 --visibility-timeout 300
```

访问：

```text
http://127.0.0.1:8000/docs
```

运行测试：

```bash
python -m pytest -q
```

## 9. 线上部署（宝塔）

当前线上入口：

```text
https://notify.zgm2003.cn
```

健康检查：

```text
https://notify.zgm2003.cn/health
```

已验证环境：

```text
Python 3.12.13
15 passed
https://notify.zgm2003.cn/health -> {"status":"ok"}
```

服务器项目目录：

```bash
/www/wwwroot/rc_zuoguangming
```

线上运行时使用项目内虚拟环境：

```bash
cd /www/wwwroot/rc_zuoguangming
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

宝塔中使用两个常驻进程：

### API 进程

```text
名称：notify-api
运行目录：/www/wwwroot/rc_zuoguangming
进程数量：1
```

启动命令：

```bash
/www/wwwroot/rc_zuoguangming/.venv/bin/python -m uvicorn src.app.main:app --host 127.0.0.1 --port 8000
```

### Worker 进程

```text
名称：notify-worker
运行目录：/www/wwwroot/rc_zuoguangming
进程数量：1
```

启动命令：

```bash
/www/wwwroot/rc_zuoguangming/.venv/bin/python -m src.app.worker_runner --poll-interval 1 --batch-size 10 --timeout 5 --visibility-timeout 300
```

Nginx 反向代理：

```text
notify.zgm2003.cn -> http://127.0.0.1:8000
```

HTTP 会跳转到 HTTPS，HTTPS 请求由 Nginx 转发到本地 FastAPI 服务。

宝塔进程管理器的完整可复制启动命令见：

```text
docs/baota-process-manager.md
```


## 9.1 Docker / Postgres 并发验证

如果要验证服务器并发路径，不要只跑 SQLite。使用 Docker Compose 启动 Postgres、API 和 worker：

```bash
docker compose up --build
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

只启动 Postgres 用于并发 claim 检查：

```bash
docker compose up -d postgres
```

然后在本机运行：

```bash
$env:DATABASE_URL="postgresql+psycopg://notify_user:notify_password@127.0.0.1:5432/notify_db"
python scripts/postgres_concurrency_check.py
```

成功输出应该包含：

```text
duplicate_claims=0
```

这验证的是 Postgres 多 worker claim 不重复，不是宣称系统已经完成完整生产压测。完整压测还需要对 API 创建吞吐、worker 投递吞吐、供应商限流和失败率做单独测试。

## 10. 代码结构

```text
src/app/
  config.py        # 配置
  database.py      # SQLAlchemy engine/session/schema
  models.py        # 数据模型和状态常量
  schemas.py       # API 请求/响应模型
  repository.py    # 数据库读写和状态流转
  retry_policy.py  # 纯函数重试策略
  dispatcher.py    # HTTP 投递
  worker.py        # worker 编排
  worker_runner.py # 常驻 worker 进程入口
  main.py          # FastAPI routes

scripts/
  postgres_concurrency_check.py # Postgres 多 worker claim 验证

tests/
  test_retry_policy.py
  test_notification_flow.py
  test_database_config.py
  test_postgres_claim.py
  test_production_config.py
  test_docker_assets.py
```

## 11. 为什么第一版不用 MQ

Kafka/RabbitMQ 当然能做，但第一版不是“不知道 MQ”，而是**没有证据证明必须引入 MQ**。

数据库队列已经能满足第一版最关键的可靠性：

- 持久化
- 可查询
- 可重试
- 有状态流转
- 有 attempt 证据
- 部署简单

未来流量增长时，可以演进：

1. SQLite -> Postgres
2. 增加并发 worker 和行锁 claim
3. 增加 per-vendor 限流
4. 引入 RabbitMQ/Kafka
5. 增加 metrics、tracing、alerting
6. 增加管理后台和人工 replay


## 11.1 服务器并发版

当前代码支持通过 `DATABASE_URL` 切换数据库：

```bash
# 本地默认
DATABASE_URL=sqlite:///./notification_service.db

# 服务器并发版
DATABASE_URL=postgresql+psycopg://notify_user:password@127.0.0.1:5432/notify_db
```

SQLite 适合本地运行和单 worker 演示；Postgres 适合服务器上多 API worker、多投递 worker。

Postgres 下任务 claim 使用行级锁：

```sql
FOR UPDATE SKIP LOCKED
```

这个设计避免多个 worker 抢到同一条 due notification。也就是说，我们没有把“高并发”吹成口号，而是把并发边界落在数据库行级锁上。

详细生产架构见 `docs/production-architecture.md`。

## 12. 当前验证

核心行为由自动化测试覆盖：

- retry policy：成功、瞬时失败、永久失败、次数耗尽、退避上限
- repository：创建、查询、claim、attempt 记录、stale processing 恢复
- worker：成功投递、瞬时失败重试、永久失败停止
- worker runner：常驻循环、poll interval 和停止条件
- API：创建通知并查询状态

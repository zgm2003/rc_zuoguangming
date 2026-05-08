# 宝塔进程管理器部署命令

> 不要把真实数据库密码提交到仓库。下面所有命令里的 `<DB_PASSWORD>` 替换成宝塔 PostgreSQL 数据库密码。

## 1. 基本信息

项目目录：

```text
/www/wwwroot/rc_zuoguangming
```

PostgreSQL：

```text
数据库名：notify_db
用户名：notify_user
访问权限：本地服务器
```

DATABASE_URL：

```text
postgresql+psycopg://notify_user:<DB_PASSWORD>@127.0.0.1:5432/notify_db
```

## 2. 先在 SSH 初始化

```bash
cd /www/wwwroot/rc_zuoguangming
git pull origin master
source .venv/bin/activate
python -m pip install -r requirements.txt
```

初始化 PostgreSQL 表：

```bash
DATABASE_URL='postgresql+psycopg://notify_user:<DB_PASSWORD>@127.0.0.1:5432/notify_db' python -c "from src.app.database import init_db; init_db(); print('db ok')"
```

看到：

```text
db ok
```

说明数据库表初始化成功。

如果历史数据里已经存在重复的 `idempotency_key`，初始化不会直接炸，但会跳过创建唯一索引并打 warning；这时先把重复数据清掉，再重跑初始化。

## 3. 进程一：notify-api

宝塔进程管理器填写：

```text
名称：notify-api
启动用户：root
运行目录：/www/wwwroot/rc_zuoguangming
进程数量：1
备注：FastAPI notification API
```

启动命令，整条复制：

```bash
/usr/bin/env DATABASE_URL='postgresql+psycopg://notify_user:<DB_PASSWORD>@127.0.0.1:5432/notify_db' /www/wwwroot/rc_zuoguangming/.venv/bin/python -m uvicorn src.app.main:app --host 127.0.0.1 --port 8000
```

## 4. 进程二：notify-worker

宝塔进程管理器填写：

```text
名称：notify-worker
启动用户：root
运行目录：/www/wwwroot/rc_zuoguangming
进程数量：1
备注：notification delivery worker
```

启动命令，整条复制：

```bash
/usr/bin/env DATABASE_URL='postgresql+psycopg://notify_user:<DB_PASSWORD>@127.0.0.1:5432/notify_db' /www/wwwroot/rc_zuoguangming/.venv/bin/python -m src.app.worker_runner --poll-interval 1 --batch-size 10 --timeout 5 --visibility-timeout 300
```

这里必须是：

```text
--poll-interval 1
```

不要写成：

```text
--poll-interval interval
```

## 5. Nginx 反向代理

宝塔站点：

```text
notify.zgm2003.cn
```

反向代理目标：

```text
http://127.0.0.1:8000
```

## 6. 验证

服务器本机：

```bash
curl http://127.0.0.1:8000/health
```

公网：

```bash
curl https://notify.zgm2003.cn/health
```

预期返回：

```json
{"status":"ok"}
```

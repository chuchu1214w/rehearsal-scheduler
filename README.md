# 舞团排练排程系统(rehearsal-scheduler)

为舞团路演安排多首曲目排练的排程工具:成员在线填写空闲时间,管理员一键求解(OR-Tools CP-SAT 分层优化),无解时给出诊断与最小调整建议;支持手动微调、锁定重排、版本对比和日历订阅。

**当前状态:M0(求解包)、M1(账号、演出、人员、曲目、特殊要求)、M2 的大部分(成员涂格填报、管理员进度与代填)、M3(一键求解、无解诊断)与 M4(课程表式周日历、当天日程、发布、成员端我的 / 全体切换、日历订阅)已完成,界面按 `design/手机UI草图` 实现;拖拽微调、锁定重排、版本对比(M5)与站内通知(M6)尚未接入。** 交互与视觉依据见 [交互设计.md](交互设计.md),里程碑与设计见 [开发文档.md](开发文档.md)。

## 本机运行

需要 Python 3.12 和 Node.js。在仓库根目录执行:

```bash
./scripts/start.sh
```

脚本会创建虚拟环境、安装依赖、首次构建前端并启动服务。浏览器打开 <http://localhost:8000>,第一次会进入「首次设置」创建管理员账号。

想先看演示数据(仅对空数据库有效;创建管理员 `demo / demo12345`、14 名成员账号(用户名 = 昵称,密码 `season2026`)、12 首曲目、3 条特殊要求,并为 11 人填好空闲;演出日期默认 30 天后):

```bash
./.venv/bin/python scripts/seed_demo.py
```

开发模式(后端自动重载 + 前端热更新,前端在 <http://localhost:5173>):

```bash
./scripts/dev.sh
```

数据保存在 `data/app.db`,不会提交到仓库;备份就是复制这个文件。不需要任何环境变量,可选项见 `.env.example`(例如 `SOLVER_WORKERS` 限制求解线程数)。数据库结构升级时启动会自动迁移,不用删库。

求解在独立子进程里跑,页面每 1.5 秒刷新进度;14 人 12 曲的演示数据几秒内出结果。**改动后端代码后要重启 `start.sh`** 才会生效。

日历订阅链接形如 `http://<地址>/cal/<令牌>.ics`(手机上用 `webcal://`);要让成员在手机上订阅成功,服务必须能从手机访问到,并把 `PUBLIC_BASE_URL` 设成那个地址(例如 `http://192.168.1.10:8000`)。

## 测试

```bash
cd backend && ../.venv/bin/python -m pytest
```

包含求解包测试与接口测试;其中权限矩阵测试会枚举全部 API 端点,确保匿名返回 401、普通成员访问管理接口返回 403。

前端类型检查与构建:

```bash
cd frontend && npm run build
```

## 求解器命令行(M0)

求解包可以脱离网页单独使用:

```bash
cd backend && ../.venv/bin/python -m solver sample -o sample.json
```

```bash
cd backend && ../.venv/bin/python -m solver synth sample.json -o input.json --density 0.7 --seed 42
```

```bash
cd backend && ../.venv/bin/python -m solver solve input.json -o result.json
```

其他命令:`validate`(用校验器检查一份排练表)、`diagnose`(只做无解诊断)。输入文件格式见 `backend/solver/serialization.py` 的模块说明。

## 仓库结构

| 路径 | 说明 |
|---|---|
| `开发文档.md` | 需求、算法、数据模型、架构、视觉规范、里程碑 |
| `backend/app/` | FastAPI 后端(账号、演出、人员、曲目、特殊要求、空闲填报、求解前检查) |
| `backend/solver/` | 排程求解包(纯 Python + OR-Tools,不依赖数据库或 Web 框架) |
| `backend/tests/` | 测试(pytest) |
| `frontend/` | Vite + React + TypeScript 前端(自写组件,按 `design/手机UI草图` 实现;移动优先,≥ 900px 桌面布局) |
| `design/` | logo 参考图、设计令牌 `tokens.css`、手机 UI 草图(视觉基准)、类图 SVG |
| `scripts/` | `start.sh` 一键启动、`dev.sh` 开发模式、`seed_demo.py` 演示数据 |
| `untitled11.py` | Colab 原型脚本,仅作参考;已被 `backend/solver` 取代 |

## 隐私说明

本仓库为公开仓库,只放代码与文档。`.gitignore` 已排除数据库、`.env`、Excel、求解输入输出等可能含真实成员数据的文件,请勿提交成员的真实空闲时间。

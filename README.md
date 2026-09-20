# 舞团排练排程系统(rehearsal-scheduler)

为舞团路演安排多首曲目排练的排程工具:成员在线填写空闲时间,管理员一键求解(OR-Tools CP-SAT 分层优化),无解时给出诊断与最小调整建议;支持手动微调、锁定重排、版本对比和日历订阅。

**当前状态:M0(求解包)与 M1(账号、名册、活动、曲目 + 网页界面)已完成;空闲填报、求解、排练表在后续里程碑。** 里程碑与设计见 [开发文档.md](开发文档.md)。

## 本机运行

需要 Python 3.12 和 Node.js。在仓库根目录执行:

```bash
./scripts/start.sh
```

脚本会创建虚拟环境、安装依赖、首次构建前端并启动服务。浏览器打开 <http://localhost:8000>,第一次会进入「首次设置」创建管理员账号。

想先看演示数据(仅对空数据库有效,会创建管理员 `demo / demo12345` 和示例名册、曲目):

```bash
./.venv/bin/python scripts/seed_demo.py
```

开发模式(后端自动重载 + 前端热更新,前端在 <http://localhost:5173>):

```bash
./scripts/dev.sh
```

数据保存在 `data/app.db`,不会提交到仓库;备份就是复制这个文件。不需要任何环境变量,可选项见 `.env.example`。

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
| `backend/app/` | FastAPI 后端(账号、名册、活动、曲目) |
| `backend/solver/` | 排程求解包(纯 Python + OR-Tools,不依赖数据库或 Web 框架) |
| `backend/tests/` | 测试(pytest) |
| `frontend/` | Vite + React + TypeScript + Ant Design 前端 |
| `design/` | logo 参考图与设计令牌 `tokens.css` |
| `scripts/` | `start.sh` 一键启动、`dev.sh` 开发模式、`seed_demo.py` 演示数据 |
| `untitled11.py` | Colab 原型脚本,仅作参考;已被 `backend/solver` 取代 |

## 隐私说明

本仓库为公开仓库,只放代码与文档。`.gitignore` 已排除数据库、`.env`、Excel、求解输入输出等可能含真实成员数据的文件,请勿提交成员的真实空闲时间。

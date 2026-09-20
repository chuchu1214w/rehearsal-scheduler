# 舞团排练排程系统(rehearsal-scheduler)

为舞团路演安排多首曲目排练的排程工具:成员在线填写空闲时间,管理员一键求解(OR-Tools CP-SAT 分层优化),无解时给出诊断与最小调整建议;支持手动微调、锁定重排、版本对比和日历订阅。

**当前状态:M0 完成(求解包 + 命令行),尚无网页界面。** 里程碑见 [开发文档.md §11](开发文档.md)。

## 文档

- [开发文档.md](开发文档.md):需求决策记录、功能需求、排程算法规格、数据模型、系统架构、接口概要、视觉规范、部署方案、里程碑与验收标准。

## 仓库结构

| 路径 | 说明 |
|---|---|
| `开发文档.md` | 本项目的开发依据 |
| `backend/solver/` | 排程求解包(纯 Python + OR-Tools,不依赖数据库或 Web 框架) |
| `backend/tests/` | 测试(pytest) |
| `design/` | 视觉参考:logo 与设计令牌 `tokens.css` |
| `untitled11.py` | Colab 原型脚本,仅作参考;已被 `backend/solver` 取代 |

## 本机运行求解器(M0)

需要 Python 3.12。

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e "backend[dev]"
```

```bash
cd backend && python -m solver sample -o sample.json
```

```bash
cd backend && python -m solver synth sample.json -o input.json --density 0.7 --seed 42
```

```bash
cd backend && python -m solver solve input.json -o result.json
```

其他命令:`python -m solver validate input.json result.json` 用校验器检查一份排练表;`python -m solver diagnose input.json` 只做无解诊断。`sample` 写出的是附录 A 的示例活动(不含空闲数据),`synth` 生成的是**合成**空闲矩阵,只用于测试与演示。

运行测试:

```bash
cd backend && python -m pytest
```

## 输入文件格式(JSON)

| 键 | 说明 |
|---|---|
| `event` | 活动参数:`performance_date`、`formal_start_date`、`day_start_hour`(默认 10)、`day_end_hour`(默认 23)、`soft_daily_limit` / `hard_daily_limit`(默认 8 / 8)、`merge_visit_gap`、`free_gap`、`eval_durations`(默认 `[3, 2]`)、`eval_min_contiguous`(默认 2)、`same_song_different_days`、`difficulty_templates`、`stage_time_limit`、`workers`、`seed` |
| `members` | 成员昵称列表 |
| `songs` | 每首:`code`、`name`、`difficulty`(简单/一般/困难)、`members`、可选 `session_plan`(如 `[3, 2]`,覆盖难度模板) |
| `availability` | `{"成员": {"YYYY-MM-DD": "1110000002211"}}`,每格 `0` 不可排 / `1` 可排 / `2` 尽量避开;字符串长度 = 每日格数 |
| `rules` | `blocked_slots`(`{"日期": "all"` 或 格索引列表`}`)、`max_sessions_per_date`、`member_song_max_attendance`(`[{"member","song","max"}]`)、`focus_members`、`fixed_sessions`(`[{"song","date","start","duration","absent_member"}]`) |
| `ladder` | 缺席降级阶梯,默认 L0 严格 → L1 20% → L2 25% |
| `objectives` | 优化目标顺序,键名见 `solver/types.py` 的 `OBJECTIVE_LABELS` |

## 隐私说明

本仓库为公开仓库,只放代码与文档。`.gitignore` 已排除数据库、`.env`、Excel 等可能含真实成员数据的文件,请勿提交成员的真实空闲时间。

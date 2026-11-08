# trace-assay

**中文** | [English](README.md)

面向智能体会话轨迹的**开训前质检**。先冻结一张印记卡（要教会什么、必须拒绝什么），扫描密钥和邮箱，按家庭切分以免留出集泄漏，要求每一种印记都有足够覆盖，并生成偏好对——然后用 `FIRE` / `STRIP` / `HOLD` 决定这批语料能不能拿去训练。

这个技能不会启动训练，也不会把一次演示写成新的技能。它只告诉你：你拥有的这批语料，够不够格成为训练数据。

## 特性

- **印记卡** — 一个目标、要印上的行为、必须拒绝的行为、切分种子、留出比例、覆盖下限
- **按家庭切分** — 同一任务的两次运行留在同一侧；至少拿出一个家庭做留出
- **密钥扫描** — 私钥、云厂商与供应商令牌、Bearer 头、看起来像 JWT 的字符串、带密码的地址、邮箱
- **质量过滤** — 噪声、中止和禁入的轨迹不会进入训练；完全重复和同一侧的近重复会被去掉
- **泄漏检查** — 近重复同时出现在训练集和留出集时会得到 `HOLD`
- **偏好对** — 一次成功加上 `rejected_text`，或同一家庭里共享印记的一条 `fail`
- **标准库助手** — `scripts/traceassay.py`（`lint` / `check` / `demo`）以及单元测试

## 安装

```bash
git clone https://github.com/fangdididi/trace-assay.git
cd trace-assay
```

### Claude Code / Codex / Cursor 等智能体

- 把本仓库放到（或符号链接到）智能体加载技能的目录，**或者**
- 打开这个文件夹并对智能体说：“在用这些会话日志做微调之前，先按 SKILL.md（trace-assay）执行。”

不需要 API 密钥。助手只用 Python 3 标准库。

## 用法

```bash
# 形状检查
python3 scripts/traceassay.py lint templates/assay.json

# 完整质检
python3 scripts/traceassay.py check examples/debug-fire.json
python3 scripts/traceassay.py check examples/debug-strip.json
python3 scripts/traceassay.py check examples/debug-hold.json
python3 scripts/traceassay.py check examples/debug-leak.json

# 内置干净示例
python3 scripts/traceassay.py demo

# 测试
python3 -m unittest discover -s tests -v
```

典型流程：

1. 在 `assay.json` 里写好印记卡，并填入你拥有的轨迹。
2. 先 `lint` 再 `check`，然后根据 `FIRE` / `STRIP` / `HOLD` 分支。
3. 得到 `FIRE` 时，只使用列出的 `train` 编号来训练，不要动 `holdout`。

## 示例

| 文件 | 预期结果 |
| --- | --- |
| `examples/debug-fire.json` | `FIRE`（含两对偏好样本） |
| `examples/debug-strip.json` | `STRIP`（供应商密钥 + 邮箱） |
| `examples/debug-hold.json` | `HOLD`（覆盖未达到下限） |
| `examples/debug-leak.json` | `HOLD`（训练集复述了留出集轨迹） |

## 文件结构

```
trace-assay/
├── SKILL.md
├── SKILL.zh-CN.md
├── README.md
├── README.zh-CN.md
├── LICENSE
├── scripts/traceassay.py
├── templates/assay.json
├── examples/
└── tests/test_traceassay.py
```

## 许可证

MIT © fangdididi

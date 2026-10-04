# 设计：全话轮监听 + 智能检索路由

日期：2026-10-04
状态：待评审
前置：已批准的产品规划（对话内，2026-10-04）——触发边界=实质话轮；检索路由=距离阈值+词表双保险；陈述类=生成接话。

## 1. 背景与问题

现状：`looks_like_question`（问号/关键词）命中才触发生成；`rag.trigger()` 无条件检索 k=5 并注入 prompt。三个断层：

1. 开放题（"介绍下你的项目经历"）常不含关键词，自动作答不触发；
2. 八股库对开放题必然弱相关，仍被注入 → 模型硬凑资料，答案跑偏；
3. 面试官陈述/铺垫时助手沉默，"此刻该接什么话"正是实时辅助价值场景。

## 2. 目标 / 非目标

**目标**：实质话轮全部触发生成；弱相关资料不注入；陈述类生成可照读接话；技术题体验零回退。

**非目标**：不做 LLM 预分类（本地检索毫秒级免费，多一次调用不值）；不加设置项（"自动作答"开关即模式切换）；不做忙时排队补答（v2 备选）。

## 3. 方案总览

```
ASR 段落(1.5s 停顿分段=话轮)
  → classify_turn(text)                    # core/heuristics.py，纯函数
     chatter → 丢弃（不触发）
     其余   → 触发生成
  → rag.trigger():
     turn_class = classify_turn(话轮文本)
     statement → 不检索
     其他      → 检索 k=3（本地；2026-10-05 修订：5→3，prompt 更短、首字延迟更低，
                 RRF 排序下 top-3 覆盖度足够，弱相关块本就会被距离阈值拦下）
        use_refs = 有结果 且 (距离可靠 ? top_distance ≤ REF_DIST_MAX
                                        : FTS 命中)          # HashEmbedder 降级
        FTS 越过：查询含 ≥4 字词项精确命中时，可越过距离阈值（双保险）
  → build_messages(mode = refs | generic | statement)       # core/generator.py
  → 流式生成；rag.last_notice 供气泡标注
```

**对已批准规划的一处修订（需评审确认）**：原规划"open 类直接不检索"；实现改为**统一检索、由距离阈值决定注入**。理由：检索本地毫秒级、零费用，而"跳过"会堵死"简历/项目文档入库后开放题命中资料"这条质量路径；阈值已能精确识别"没有真相关资料"。词表的角色调整为：驱动 prompt 分支与触发过滤，不拦截检索。

## 4. 话轮分类引擎（core/heuristics.py）

```python
def classify_turn(text: str) -> str:
    """'chatter' | 'open' | 'question' | 'statement'"""
```

判定顺序（先到先得）：

1. 纯标点/无文字字符 → `chatter`（管线已滤一层，此处兜底）；
2. 去首尾空白后 < 8 字 → `chatter`（寒暄/短反馈几乎都低于此线）；
3. < 16 字 且命中 CHATTER_WORDS（嗯/好的/谢谢/下一题/继续/明白/不错…）且**不含**强疑问信号（问号结尾或 什么/怎么/怎样/如何/为什么/哪些/哪个）且**不含** OPEN_ENDED_WORDS → `chatter`；
4. 命中 OPEN_ENDED_WORDS（自我介绍/项目经历/职业规划/离职原因/优缺点/你的优势/性格/加班/期望薪资/聊聊你/说说你/谈谈你/遇到的困难…）→ `open`（**先于** question：这些词本质是个人指向的开放题，即使带"介绍一下"动词）；
5. 现有 `looks_like_question`（问号结尾或 QUESTION_WORDS）→ `question`；
6. 其余 → `statement`。

`looks_like_question` 保留不删（被既有测试与语义依赖）。

### 测试矩阵（验收用例）

| 输入 | 期望 |
|---|---|
| "嗯好的" | chatter |
| "那我们继续下一题" | chatter |
| "好的我们了解一下" | chatter（短+过渡词，无强问句信号） |
| "你了解 Redis 吗" | question（问句信号豁免 chatter 规则） |
| "介绍一下你的项目经历" | open |
| "讲讲你的职业规划" | open |
| "Redis 持久化怎么做的" | question |
| "我们团队主要做 ToB 业务" | statement |

## 5. 检索路由（core/retriever.py + core/rag.py）

### 5.1 真距离透传（retriever.py）

- `Retrieved.score` 现为 RRF 排名占位符（恒 1/(60+rank)），**不可用于阈值**；
- `kb.vector_search` 已返回 `(chunk_id, L2_distance)`——retriever 记录 `self.last_top_distance: float | None`（最优向量的原始 L2 距离；无向量结果时 None）；
- 新属性 `distances_reliable: bool`（`isinstance(embedder, OnnxEmbedder)`；HashEmbedder 的距离无意义）。

### 5.2 注入判定（rag.py）

```python
REF_DIST_MAX = 1.05   # L2（单位向量）⇔ cos ≥ 0.45；彩排模式校准
```

- `statement` → 不检索；
- 其他 → `retrieve(k=3)`；
- `use_refs = bool(contexts)` 且满足其一：
  - 距离可靠 且 `last_top_distance ≤ REF_DIST_MAX`；
  - 任一检出 chunk 的文本含查询中 ≥4 字词项（子串判定，防阈值误杀真命中）；
  - 距离不可靠（Hash 降级）→ 维持现状：有结果即注入。

## 6. 生成分支（core/generator.py）

`build_messages(question, contexts, history, mode)`，三模式共用"口语化、可照读、4-6 点、≤250 字"的基座：

| mode | 触发条件 | system 指令差异 |
|---|---|---|
| `refs` | use_refs=True | 现状不变（优先使用参考资料） |
| `generic` | use_refs=False（含 open 无命中、question 无命中） | 知识库无相关资料，凭自身知识与经历回答；**禁止虚构资料引用** |
| `statement` | turn_class=statement | 面试官在陈述/铺垫，非提问；给出此刻最该说的自然回应，一两句即可，顺势带出自己的优势 |

### 气泡标注（rag.last_notice，worker 经 notice 信号透出）

| 场景 | 标注文本 |
|---|---|
| refs | 基于知识库 · N 条资料 |
| generic + open | 开放题 · 未用资料 |
| generic + question | 通用回答（知识库无命中）（沿用现文案） |
| statement | 接话 · 未用资料 |

## 7. 触发与交互（app/main_window.py）

- `_on_subtitle` 触发条件：`looks_like_question(t)` → `classify_turn(t) != "chatter"`；
- 忙时丢弃（现状）；每话轮一个回答气泡（现状延伸）；"自动作答"开关语义不变。

## 8. 涉及文件与测试

| 文件 | 变更 | 测试 |
|---|---|---|
| core/heuristics.py | +`classify_turn`、CHATTER_WORDS、OPEN_ENDED_WORDS | 分类矩阵（§4） |
| core/retriever.py | +`last_top_distance`、`distances_reliable` | 真/假 embedder 两路 |
| core/rag.py | 路由 + `last_notice` | statement 不检索 / 距离超限不注入 / FTS 越过 / Hash 降级 |
| core/session.py | `extract_question` 改名 `extract_turn`（语义=话轮文本，rag 同步） | 既有 session 测试随改 |
| core/generator.py | `build_messages` 三模式 | 各 mode 的 prompt 断言 |
| app/main_window.py | 触发条件替换 | statement/open 触发、chatter 不触发（更新既有用例） |
| app/workers.py | notice 改透 `rag.last_notice` | 透传断言 |

UI（ui_chat.py）无需改动——note 标注复用现有 notice 机制。

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| 闲聊误触发 | 长度门槛 + chatter 词表 + 宁缺勿滥取向 |
| 陈述类接话质量不稳 | prompt 限一两句，不强行展开 |
| 每话轮一次 LLM 调用费用上升 | 1h 面试约 50-100 实质话轮；自动作答开关随时关 |
| 阈值误杀真命中 | FTS ≥4 字命中越过阈值；REF_DIST_MAX 彩排校准 |
| 陈述类不该带资料 | statement 分支不检索，从源头隔离 |

## 10. 验收标准

1. §4 分类矩阵全过；
2. 彩排跑真实录音：实质话轮触发率 100%、chatter 触发率 0；
3. 开放题（无简历入库）标注「开放题 · 未用资料」，答案无硬凑资料痕迹；
4. 简历入库后开放题命中资料，走 refs 模式；
5. 技术题命中时行为与现状一致；
6. 全量 pytest 通过。

# 记忆投递机制设计：索引式注入、压缩补投、读侧可观测

> 2026-10-23。状态：待实现（卡片 `#2126`，project `using-memory`）。
> 关联：`SKILL.md` 的 Session Snapshot / Hook Behaviour 两节、`packages/pi/extensions/umem/`、`scripts/hooks/memory_hook_common.py`、`scripts/memory_tool.py`。

## 1. 为什么要改

现在的机制对"写"是闭环的（stop gate 会拦），对"读"完全没有保证也没有观测。长会话里最需要记忆的时候，恰好是记忆最不可见的时候。下面是实测，不是推测。

### 1.1 注入会丢掉最老的内容（主要缺陷）

`scripts/memory_tool.py:695` 的 `_brief_tail()` 语义是**保留尾部、丢掉头部**，上限 `BRIEF_DURABLE_MEMORY_LIMIT = 4000`（`:687`）。

用本机真实数据量一下（`~/.memories/main`）：

| 文件 | 实际大小 | 注入预算 | 结果 |
|---|---|---|---|
| `MEMORY.md` | 17509 chars / 51 条 | 4000 chars | **77% 不可见**，且丢的是最早写、最经时间检验的部分 |
| `PREFERENCES.md` | 3878 chars / 21 条 | 4000 chars | 已在临界，再写两条就开始从最老的一条丢起 |
| `docs/index.json` | 21k chars / 66 篇 | `brief_sources()` 整块丢弃 | **66 篇文档对模型完全不可见** |
| `log_entries` | 今日+昨日 | 每条 `BRIEF_LOG_TEXT_LIMIT = 350` | 正文截断，可接受 |

保留方向是反的：新写入、尚未验证的条目一定在，最早、最稳定的规则最先消失。

### 1.2 三个 host 看到的东西不一样

| host | 注入内容 | 代码 |
|---|---|---|
| Pi | reminder + **全量偏好** + 截断记忆 + 近期操作 | `packages/pi/.../index.ts:68 renderSnapshot` + `:487 sessionSnapshot`（`load --json --brief`） |
| Claude / Codex | reminder + **4 条**关键词打分挑出的偏好 + 蒸馏候选；**无 MEMORY、无 docs** | `scripts/hooks/memory_hook_common.py:1011` SessionStart 分支 → `:744 fetch_session_start_snapshot` → `:219 render_preference_summary(max_items=4)` |

`_score_preference_line`（`:205`）偏向 `reply/language/style/format/always/never` 等词。像"多 Agent 共享仓库一律用 git worktree 隔离"这种**操作规范**不含这些词，在 Claude/Codex 上就选不中。

### 1.3 Pi 在压缩后不补投（最致命的时序缺口）

`packages/pi/extensions/umem/hooks.ts:306`：

```ts
pi.on("session_before_compact", () => undefined as never);   // 注释写 "no-op, deliberately"
```

而 Codex / Claude 的 `SessionStart` matcher 是 `startup|resume|clear|compact`，它们会补。

本机一次 8 天会话的 transcript 实证（`~/.pi/agent/sessions/...iceberg.../2026-10-15T07-30-49-798Z_*.jsonl`）：

```
3992  2026-10-23T02:38:26  custom_message (customType=umem)   ← 全程唯一一次注入
3996  2026-10-23T02:39:20  compaction                        ← 1 分钟后压缩
4770  2026-10-23T04:13:32  compaction                        ← 再次压缩
1830  2026-10-19T09:48:32  compaction                        ← 更早的一次
```

结论：**注入一次，之后靠压缩摘要"顺带保留"**，机制上没有任何保证。

### 1.4 读侧零观测

`~/.memories/main/STATS/local-main.json` 真实内容：

```json
{"sessions":816,"log_entries_user":1589,"log_entries_auto":600,
 "stop_blocks":671,"stop_throttled_passthrough":3502,"cumulative_human_turns":1390, ...}
```

有 `sessions`、写入次数、拦截次数，**没有任何 `load` / `search` / 注入 / 注入失败 的计数**。系统花 671 次 block 强制"写"，却无法回答"读发生过没有"。

### 1.5 失败与"没有记忆"不可区分

Pi 侧 `try { ... } catch {}`（`hooks.ts` 的 `onSessionStart`）与 `sessionSnapshot` 的 `return null`；Python 侧 `except Exception: return None`。CLI 坏掉时模型看到的是"没记忆"，不是"记忆没加载"。

### 1.6 偏好与记忆没有结构与去重

`PREFERENCES.md` 是 append-only + 日期前缀，21 条靠人工维护，没有 `pinned/scope/expires`，也没有近似重复检测。实测事故：同一条 worktree 规范被同时写进 `PREFERENCES.md` 和 `MEMORY.md`，一天后才手工删掉副本——机制没有拦。

## 2. 不变量（先定契约，再改实现）

| 编号 | 不变量 | 度量方式 |
|---|---|---|
| **I1 送达** | 每个上下文纪元（session 开始、**压缩之后**、reload）至少投递一次快照 | Pi 压缩后必须出现一条 `customType=umem` 消息 |
| **I2 截断可见且按优先级** | 裁剪必须显式标注；保留顺序由 pinned/scope/新鲜度决定，不按文件位置 | 快照头部报出"多少条、进了多少、截掉多少" |
| **I3 读可观测** | 注入次数、注入失败数、`load`/`search` 调用数进 STATS | `umem status` 能看到比值与趋势 |
| **I4 失败可见** | 注入失败产出一条可见短提示 | 失败时快照含 `## Memory not loaded` 段 |
| **I5 优先级可声明** | 条目支持 `pinned` / `scope:repo\|global` / `expires` | 写入解析失败要有明确报错 |
| **I6 单一事实源** | 一条规则只住一处；双写可被巡检发现 | `maintain --audit` 列出跨文件近似条目 |
| **I7 host 一致** | 三个 host 至少投递同一"最小核心集"，差异只允许加 | 同一 fixture 下三 host 的注入文本除 header 外一致 |

## 3. 设计

### 3.1 核心决定：注入形态从"正文截断"换成"目录 + 按需正文"

现在的做法是"把 MEMORY.md 的尾部 4000 字符塞进去"。改成：

- **记忆按条目索引化**：每条只投 `## 标题 · tag · 日期`（可选 `needs_detail` 标记），51 条约 2.5k chars；
- **文档按索引化**：只投 `title · type · 一行 summary`，并按当前 cwd 的 project 过滤（66 篇 → 当前仓库通常 <10 条）；
- **偏好保持正文**（这是最需要"照做"的东西），但受预算与优先级约束；
- **日志保持**今日+昨日、每条 350 chars（现状即可）。

正文通过 `umem search` / `load --doc <slug>` 取。快照头部必须说明这是索引：

```
<!-- umem snapshot @2026-10-23T04:20:11+08:00 | prefs 21 (pinned 6) | memory 51 (index) | docs 9 of 66 (project=iceberg) | log 2d 13 | truncated: prefs 0, memory 51 -->
```

### 3.2 架构简化：渲染只在 Python 侧做一次

今天 Pi 有 `index.ts:68 renderSnapshot`（TS），Claude/Codex 有 `render_preference_summary`（Python），两套渲染 = 天然分叉（这正是 1.2 的根因）。

改为：

1. 新增 `umem load --digest [--format=markdown|json]`，Python 产出**成品文本**（含 header、各段、截断标注）；
2. Pi 的 `sessionSnapshot` 直接把该文本当作消息内容，删掉 TS 渲染器（`renderSnapshot` 退化为透传或删除）；
3. Claude/Codex 的 `SessionStart` 用同一个函数，不再走"4 条偏好"的旧路径。

这样 I7 由结构保证，而不是靠两边各自维护。

### 3.3 Pi 压缩后补投

`session_before_compact` 里判断"这次压缩是否真的丢了消息"（事件里带消息数/token 数则据此判断，否则一律补投），补投方式与 session 开始一致：`pi.sendMessage({customType: UMEM_CUSTOM_TYPE, content}, {deliverAs: "nextTurn"})`。

成本控制：只在压缩有损时投；同一 turn 内去重（用现有 `state` 记录最后注入的 epoch/turn）。

### 3.4 读侧与注入统计

在 `bump_stats` 加：

| 计数 | 何时 +1 |
|---|---|
| `snapshot_injects` | 每次成功注入（Pi 的 `session_start`/压缩补投，Claude/Codex 的 SessionStart） |
| `snapshot_failures` | 渲染或 CLI 失败 |
| `load_calls` / `search_calls` | `umem load` / `umem search` 被调用（tool 或 CLI 都算，但注入自身用的 `load` 要排除，否则计数失真） |
| `digest_truncated_*` | 每次注入被截掉的偏好/记忆条数 |

`umem status` 增加一行：`inject:read = snapshot_injects : (load_calls + search_calls)`，并解释这是**失衡信号而非质量指标**。

### 3.5 偏好的结构与淘汰顺序

条目语法向后兼容（老条目无标记 = `scope:global`、无过期）：

```
- [2026-10-23] [pinned] 与用户交流时始终使用简体中文回复。
- [2026-10-23] [scope:iceberg] [expires:2027-01-01] 共享工作树里一律用 git worktree 隔离每张卡。
```

注入时的淘汰顺序（先砍不重要的）：`expires 已过` → `scope 不匹配当前 cwd` → 最老且未被复用的。`pinned` 永不淘汰（超预算则报错提示人工整理，而不是静默丢）。

写入时（`write-preference`）：
- 解析标记，非法标记明确报错；
- 与现有条目做近似重复检测（去日期/标记后 normalized 余弦或 token Jaccard 阈值），命中则**提示合并**而不是直接 append；
- 检测 `PREFERENCES.md` 与 `MEMORY.md` 的跨文件近似条目（I6）。

### 3.6 `maintain --audit`（第三层）

只读巡检，输出待人工裁决清单：

1. 语义矛盾：同一 scope 下"始终 X"与"不要 X"（关键词对匹配，近似即可，宁可漏报）；
2. 跨文件重复：PREFERENCES vs MEMORY 的近似条目；
3. 过期：`expires` 已过的偏好；
4. 失效引用：`files` 指向不存在的路径（已有能力，纳入统一报告）；
5. 长期未复用的 pinned 条目（可选，需要读侧计数支撑）。

审计**不自动修改**任何文件。

## 4. 验收标准

| 项 | 验收 |
|---|---|
| I1 | Pi 侧测试：触发 `session_before_compact` 后，下一条消息包含 `customType=umem` 且内容含 header；同一 turn 不重复注入 |
| I2 | fixture 记忆库（≥60 条记忆 + ≥20 篇 docs）下，注入文本必须包含**全部**记忆标题与筛选后的文档标题；header 的 `truncated:` 数字与实际裁剪一致 |
| I3 | 跑一次 `load`、一次 `search`、一次注入后，`STATS` 三个计数各 +1；注入内部调用的 `load` 不增加 `load_calls` |
| I4 | 把 CLI 指向不存在的路径，注入文本必须含 `## Memory not loaded` 且附原因 |
| I5 | `write-preference` 对 `[scope:foo]` 合法、对 `[scope:]` 报错；重复条目提示合并且不写入 |
| I6 | `maintain --audit` 在同一规则双写时能列出两处路径与行号 |
| I7 | 同一 fixture 下 Pi 与 Claude 注入文本除 header 的时间戳外逐字节一致 |

测试落点：`tests/`（Python：`--digest` 渲染、偏好解析与淘汰、audit）+ `packages/pi/tests/`（TS：压缩补投、失败可见、去重）。两侧都必须跑通；`version.txt` 按约定升 minor（2.7.0 → 2.8.0）。

## 5. 不做的事

- 不改 stop gate 阈值（`detail_turn_interval`、Pi 的 30 轮 latch）——这是写侧策略，与本设计正交；
- 不改蒸馏流水线（`maintain --distill/--promote`）；
- 不引入向量检索：66 篇文档的索引足够小，关键词/scope 过滤即可；
- 不做自动修改记忆的审计（审计只出报告）；
- 不追求"记忆被正确使用"的精确度量：`load_calls` 只能证明"请求过"。

## 6. 已知弱点（实现时不要忽略）

1. **索引化会诱发"知道有、却不读正文就猜"**。必须做两件事补偿：索引条目带 `needs_detail`，且 reminder 明确"用到的条目先 `load --doc`/`search` 取正文"。
2. **`pinned/scope` 提高写入摩擦**，人可能不标。缓解：`write-preference` 按内容**提议** scope（含仓库名 → repo 级），人只需确认。
3. **压缩补投有 token 成本**（约 1–2k/次）。只在压缩有损时投。
4. **读计数会被指标化滥用**。文档与 `status` 输出都必须写明：这是失衡信号，不是质量分。
5. **跨 host 改动回归面大**：共享层 `memory_hook_common.py` 被 Codex/Claude 共用，改动必须同时验证两个 adapter（项目既有约定）。

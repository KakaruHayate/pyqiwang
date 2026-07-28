# FC《棋王》AI 算法解析

> 本文记录 `pyqiwang` 项目对 FC 游戏《棋王》人工智能的逆向结果。结论来自 ROM 静态反汇编、6502 动态执行轨迹、RAM 状态观测，以及 ROM 与无 ROM Python 原型的差分实验。
>
> 当前阶段的准确表述是：**独立 Python selector/bound 原型在既定语料上已复现 ROM depth 1–4 的最佳走法；正式 `NativeQiWangEngine` 尚未接入这套状态机，因此仍标记为 `faithful=False`。**

## 1. 总体结构

《棋王》的行棋流程由开局谱和搜索器两部分组成：

```text
当前局面
  ├─ 符合顺序开局谱 → 执行下一步谱着
  └─ 不符合或谱线结束 → 进入 $8597 搜索
                           ├─ $8886 初始化 PST 局面分
                           ├─ $8701 生成根候选
                           ├─ 按难度执行 1–4 轮根迭代
                           └─ 返回 $C0/$C1 最佳走法
```

ROM 路径由 `QiWangEngine` 通过 6502 模拟器忠实执行。脱离 ROM 的研究路径把棋规、PST、开局谱、候选顺序和搜索状态机逐项翻译为 Python，并始终使用 ROM 路径作为 oracle。

## 2. 棋盘与棋子编码

### 2.1 12 步长棋盘

位置编码为：

```text
pos = file * 12 + rank
file = 0..8
rank = 0..9
```

每个纵列占 12 字节，其中 10 字节是有效棋盘，另外两个是 padding。ROM 在 padding 中放置非空哨兵，因此车、炮射线自然在边界停止。Python 棋盘没有这些实体哨兵，翻译射线算法时必须显式检查 `Board.is_valid_pos()`，否则射线会穿过 padding 并绕到相邻纵列。

### 2.2 单元和棋子表

棋盘单元编码：

```text
$00       空格
$10+index 红方棋子
$20+index 黑方棋子
```

双方各有 16 个固定槽位：

```text
0       将/帅
1..2    车
3..4    炮
5..6    马
7..8    士
9..10   象
11..15  兵/卒
```

`$94-$A3` 保存红方 16 个位置，`$A4-$B3` 保存黑方 16 个位置。被吃棋子使用负值/`$FF` 表示。

## 3. 开局谱

ROM 在 `$CD26` 维护一条 **33 ply 的顺序开局线**。它不是“按局面哈希查表”，而是按对局历史逐步前进：

1. 对局必须从开局开始严格沿谱进行；
2. 任一方偏离后，本局不再继续套用后续谱着；
3. 33 ply 用尽后转入搜索；
4. ROM 调用者根据 carry 标志判断开局谱是否适用。

该谱线已提取到 `pyqiwang/opening_book.json`。Native 路径通过完整棋盘匹配防止偏离后误套谱。

## 4. 评价函数

### 4.1 14 张 PST

ROM 没有使用现代引擎式的复杂评价。其基础评价来自红黑双方、七类棋子各一张位置价值表，共 14 张 PST：

```text
raw = $8000
    + Σ 红方棋子 PST[棋类][位置]
    - Σ 黑方棋子 PST[棋类][位置]
```

结果是无符号 16 位值：

- 大于 `$8000`：偏向红方；
- 小于 `$8000`：偏向黑方；
- 搜索内部直接比较 raw score，而不是转换成带符号分数。

表已从 `$8886` 动态提取到 `pyqiwang/pst_tables.json`。

### 4.2 增量更新

`$8886` 只在整个搜索开始前计算一次全盘分数。此后每次试走通过被吃棋子的 PST 删除和移动棋子的 PST 差值增量更新 `$C8/$C9`，回退时恢复原值。根候选之间共享同一根局面 baseline，不会为每个候选重新全盘评价。

## 5. ROM 的 depth 含义

ROM 的 `depth` **不是传统固定 ply 深度**，而是根搜索迭代次数：

```text
depth 1 → 1 轮根迭代
depth 2 → 2 轮根迭代
depth 3 → 3 轮根迭代
depth 4 → 4 轮根迭代
```

即使 depth 1，也可能通过选择性递归进入内部 level 4、5 或更深；在现有 depth 4 轨迹中，最大内部 level 达到 11。

根迭代计数存于 `$CF`。内部节点观察到的值为：

```text
node_cf = (root_iteration - internal_level) & $FF
```

例如第四轮（`root_iteration=3`）：

```text
level 1 → CF=2
level 2 → CF=1
level 3 → CF=0
level 4 → CF=$FF
```

这使前几层执行较宽搜索，之后转入选择性搜索。

## 6. 根节点搜索

### 6.1 候选与平分规则

根候选数量保存于 `$0500`，起点数组从 `$0501` 开始，终点数组从 `$0581` 开始。候选按 ROM 生成顺序尝试。

根 incumbent 使用有限哨兵：

```text
红方：$1000
黑方：$F000
```

最佳走法更新是严格比较：

```text
红方：candidate > best 才更新
黑方：candidate < best 才更新
```

相等时不覆盖，所以平分走法保留生成顺序更早者。

### 6.2 迭代和 aspiration

第一轮按原始候选顺序搜索。后续每轮：

1. 将上一轮最佳走法作为 preferred move 先搜索；
2. 根 bound 取上一轮 best 的窄偏移：
   - 红方：`best - 50`；
   - 黑方：`best + 50`；
3. 再遍历原始候选数组；
4. try-entry 的去重状态避免 preferred move 被完整重复展开。

## 7. 每层搜索状态

搜索以 `$C6` 作为内部 level，并在多组按 level 索引的数组中维护状态：

| 概念 | 主要槽位 |
|---|---|
| active bound | `$0672/$06F2 + level` |
| previous/adjacent bound | `$0671/$06F1 + level` |
| incumbent best | `$0772/$07F2 + level` |
| child score | `$0773/$07F3 + level` |
| selector phase | `$05F2 + level` |
| primary history | `$0490/$0498 + level` |
| secondary history | `$04A0/$04A8 + level` |
| saved stack pointer | `$0572 + level` |

这些槽位不能简单等价为标准 alpha/beta。ROM 同时保留 active、previous、best 和 child，并根据递归入口交换或调整槽位。

## 8. 静态分门控与宽度切换

### 8.1 负 CF：选择性节点

当 CF 递减后为负时，节点先把当前增量 PST 分与 active/previous bound 比较：

- 某些条件下直接返回静态分；
- 否则把静态分写入 incumbent；
- 再进入 selector 候选阶段。

这类似 stand-pat 与 bound normalization，但不能完全套用标准 quiescence 或 alpha-beta 命名，因为两侧入口和槽位生命周期是 ROM 特有的。

### 8.2 非负 CF：selector prefix + full-width suffix

当 CF 非负时，节点跳过完整静态分门控，并先写入当前行棋方的有限 sentinel：

```text
红方行棋节点：$1000
黑方行棋节点：$F000
```

随后执行：

```text
selector 候选前缀
    +
按棋子槽位 0..15 的全宽走法后缀
```

它不是“非负 CF 时只做全宽搜索”，也不是“用全宽走法替代 selector”。selector 前缀仍影响候选顺序、去重、history 和 cutoff。

## 9. Selector 四阶段

ROM selector 状态按以下顺序推进：

```text
$FF → 0 → 1 → 2
```

### 9.1 `$FF`：saved-target response 与 primary history

`saved_target` 通常是上一手终点。ROM 首先尝试本方所有能到达该点的棋子，形成对上一手目标的直接响应；随后尝试 primary history move。

### 9.2 `0`：secondary history

尝试上一层保存的次级历史走法。空目标路径是否可用还受 CF 符号控制。

### 9.3 `1`：表驱动定向候选

ROM 在 `$8DC7/$903B` 使用三类表进行快速筛选：

1. 目标格掩码；
2. 带符号位移掩码；
3. 阻挡扫描步长。

扫描顺序为：

```text
目标棋子 index 升序
候选来源 index 降序
```

第一段总是扫描对手的将和两辆车（目标 index `0..2`）。当 CF 位于 ROM 允许的范围时，继续扫描目标 index `3..15`。

表驱动几何并非调用通用象棋走法生成器：

- 车要求射线上第一个占用格就是目标；
- 炮要求射线上第二个占用格就是目标；
- 马检查马腿；
- 象检查象眼；
- 将、士、兵主要由目标格和 delta 掩码筛选。

### 9.4 `2`：directed reply 与后续路径

该阶段尝试由上一手起点导出的定向响应，之后进入 selector 结束或 full-width gate。

## 10. 合法性检查与恢复

Selector 表和 history 可以产生 pseudo-legal 候选。ROM 在 `$8049` 附近进行窄合法性检查：试走后判断本方王是否仍可被对方攻击。

若不合法：

```text
试走
 → $8049 检查失败
 → $B36A / $B6F2 恢复棋盘、分数和栈
 → 不进入子节点
```

这一行为是 depth 3 最后一个分歧的根因。Python 原型最初只过滤 full-width 后缀，导致 selector 前缀中的无效应将进入递归；统一通过每节点合法集合后，depth 3 从 `7/8` 达到 `8/8`。

为了降低 depth 4 成本，实验器实现了只判断“对方是否攻击本方王所在单格”的轻量检测，并在 40 个语料局面、3,268 个生成走法上与通用 `is_in_check()` 差分验证，未发现分歧。

## 11. Seeded probe 与 alternate re-search

ROM 对候选不是一律做同一种递归，而是有两条主要路径。

### 11.1 Seeded probe

红方入口 `$B29C` 和黑方入口 `$B624` 比较 incumbent 与 active bound。在满足条件时，给子节点一个单点窗口：

```text
红方 child active = active + 1
黑方 child active = active - 1
```

子节点返回后：

```text
红方：child > active → 进入 $B424 alternate re-search
黑方：child < active → 进入 $B7AC alternate re-search
```

否则直接恢复而不做完整重搜。

### 11.2 Alternate recursion

alternate 路径交换 bound 槽位：

```text
parent(active, previous)
    → child(previous, active)
```

子节点返回后，ROM依次处理：

1. 是否改善 incumbent；
2. 是否跨过 active bound；
3. 是否跨过 previous bound；
4. 是更新 active、直接返回，还是触发 cutoff/history。

### 11.3 Active bound 收紧

当新 best 跨过 active、但尚未跨过 previous 时，ROM 把 active 更新为 best。后续候选基于新的 active 做 `±1` probe。遗漏这一状态转换会让 depth 4 搜索树膨胀数倍。

根候选也存在 seeded/alternate 行为。当前 corpus 的动态证据显示根层红黑入口并非可直接合并成一个无条件对称包装；独立实验保留了已观测到的入口差异。该规则已通过 depth 1–4 corpus，但在正式接入前仍应继续扩大随机语料验证。

## 12. History move 的真实更新时机

History 不是在每次 best 改善时更新，而只在 cutoff 恢复路径更新：

- selector `$FF`：不旋转；
- selector `2`：通常不旋转；
- selector `1`：当前 move 写入 primary；
- selector `0`：旧 primary 移到 secondary，当前 move 写 primary。

而且每层 history 会跨根候选、跨根迭代保留。若每个候选重置 history，候选顺序和剪枝都会偏离 ROM。

## 13. 当前复现结果

独立 selector/bound 原型的最佳走法一致性：

| 语料 | 一致性 |
|---|---:|
| depth 1 golden | 12/12 |
| depth 1 independent | 23/24 |
| depth 2 independent | 8/8 |
| depth 3 independent | 8/8 |
| depth 4 independent | 8/8 |

Depth 4 八个局面的结果：

| Case | ROM / Python 走法 | 节点数 |
|---|---|---:|
| random-000 | `(19,55)` | 33,938 |
| random-001 | `(39,3)` | 9,971 |
| random-002 | `(39,15)` | 18,234 |
| random-003 | `(20,13)` | 40,993 |
| random-004 | `(90,92)` | 35,667 |
| random-005 | `(12,2)` | 141,635 |
| random-006 | `(24,0)` | 14,148 |
| random-007 | `(99,100)` | 19,047 |

轻量合法性检测、局面缓存、active bound 收紧和 seeded probe 接入后，`random-000` 从约 192,872 节点降到 33,938 节点；八局可在纯 Python 下约两分钟完成。

需要注意：上述数字证明的是**当前固定 corpus 的最佳走法一致**，并不表示每个内部事件、节点数和所有候选分数都已逐指令一致。

## 14. 尚未完全确认的部分

1. depth 1 independent 的 `random-010` 仍有一处分歧：ROM `(52,53)`，原型 `(28,29)`；
2. `$A41C-$A8E4` / `$94B9-$974C` 的全宽单子 delta 顺序尚未全部逐指令翻译，目前以棋子槽位顺序加 Python 单子生成器隔离近似；
3. 根层红黑 seeded/alternate 入口差异需要更大的随机 corpus 验证；
4. 当前 depth 1–4 状态机仍位于实验工具，未接入正式 `NativeQiWangEngine`；
5. depth 5–8 是在同一算法体系上的扩展目标，不属于原 ROM 已提供的难度范围；
6. 搜索性能仍可通过 Cython、Rust 或更紧凑的增量状态进一步提升。

因此，现阶段可以说“ROM depth 1–4 的核心搜索结构已经复原，并在独立语料上高度对齐”，但不应声称“任意局面、任意内部轨迹都已经 100% 等价”。

## 15. 项目中的对应实现

| 文件 | 作用 |
|---|---|
| `pyqiwang/_engine.py` | ROM faithful 引擎入口 |
| `pyqiwang/_mos6502.py` | 6502 CPU 模拟器 |
| `pyqiwang/_harness.py` | ROM、Mapper 和子程序调用接口 |
| `pyqiwang/_board.py` | Python 棋盘、棋规、PST 评价 |
| `pyqiwang/_book.py` | 无 ROM 的 33 ply 开局谱 |
| `pyqiwang/_native.py` | 当前正式 Native 搜索骨架，尚未接入本状态机 |
| `tools/trace_root.py` | ROM 根候选、bound、selector、递归入口动态追踪 |
| `tools/experiment_selector_candidates.py` | selector 四阶段与表驱动候选翻译 |
| `tools/experiment_selector_bound.py` | depth 1–4 独立搜索状态机和 corpus 验证 |
| `tests/fixtures/rom_depth*_independent.json` | 不含 ROM 字节的差分基线 |

## 16. 验证命令

不需要 ROM 即可运行独立 corpus：

```bash
PYTHONPATH=. python tools/experiment_selector_bound.py \
  --max-depth 4 --max-nodes 500000 --verbose
```

正式 Native 和基础棋规回归：

```bash
PYTHONPATH=. python tests/test_game.py
PYTHONPATH=. python tests/test_depth2_fixture.py
PYTHONPATH=. python tests/test_root_trace.py
```

需要生成新的 ROM 动态轨迹时，使用合法持有的 ROM 文件：

```bash
PYTHONPATH=. python tools/trace_root.py \
  --fixture tests/fixtures/rom_depth4_independent.json \
  --case random-000 \
  --rom "path/to/qiwang.nes" \
  --depth 4 \
  --output trace.json
```

仓库不包含 ROM，也不应提交由指令级追踪产生的数百 MB 临时 JSON；应提交可复现工具、小型 corpus 和经过整理的结论。

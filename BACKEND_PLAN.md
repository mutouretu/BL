# 观复模拟交易系统——后端实施规划

## 1. 后端目标

后端只负责一条主链路：

`当前跟踪 → 上游信号事件 → 交易规则判断 → PAPER 模拟订单/成交 → 现金与持仓账本 → 月度交易统计`

首版不接真实券商，不管理人工交易，不做人工账本，也不负责双方账目对比。系统最终交付的是一套来源可追踪、计算可复核、结果可导出的模拟交易账本。

## 2. 核心原则

1. **信号不可变**：上游每产生一次信号，就保存一个独立事件；连续多个 B 信号不得合并或覆盖。
2. **事件可溯源**：每个模拟订单必须关联一个信号事件 ID，能够反查上游原始内容和精确时间。
3. **执行幂等**：同一信号事件重复推送、任务重试或页面重复点击，不得产生重复订单。
4. **订单与成交分离**：即使 Demo 默认立即成交，也保留订单、成交两个对象。
5. **账本原子更新**：成交、现金流水、持仓批次和当前持仓必须在同一数据库事务内完成。
6. **统计来自账本**：月度交易统计只能从成交和持仓账本计算，不能由页面硬编码或人工填写。
7. **规则参数化**：仓位、滑点、费用、最小交易单位、T+1 和重复信号处理均通过配置控制。

## 3. 推荐技术架构

Demo 阶段采用模块化单体，暂不拆微服务：

```text
Streamlit 页面
    ↓
Application Service（跟踪、信号、模拟执行、统计）
    ↓
Domain（状态机、仓位规则、费用、T+1、成本与盈亏）
    ↓
Repository / Unit of Work
    ↓
SQLite（Demo）→ PostgreSQL（正式影子运行）

测试桩 / 固定样例（首版）
    ↓
Application Service

外部信号系统（协议确定后）
    ↓
Signal Adapter
    ↓
Application Service
```

建议目录：

```text
guanfu/
  domain/
    models.py
    enums.py
    execution_rules.py
    ledger.py
    statistics.py
  application/
    tracking_service.py
    signal_service.py
    execution_service.py
    statistics_service.py
  infrastructure/
    database.py
    repositories.py
    migrations/
    signal_adapters/
    market_data_adapters/
  api/
    schemas.py
    routes.py
  jobs/
    ingest_signals.py
    expire_tracking.py
    execute_signals.py
    end_of_day.py
  ui/
    pages.py
```

首版可以继续由 Streamlit 直接调用 Application Service；接入上游系统时再增加 FastAPI，不让页面直接写 SQL。

## 4. 数据模型

### 4.1 基础配置

#### `instruments`

- `id`
- `symbol`：统一格式，如 `300377.SZ`
- `name`
- `exchange`
- `lot_size`：A 股默认 100
- `t_plus_days`：A 股默认 1
- `is_active`

#### `paper_accounts`

- `id`
- `name`
- `initial_cash`
- `cash_balance`
- `currency`
- `enabled_at`
- `is_active`

首版只有 PAPER 账户，不再保留 MANUAL 类型和配对账户字段。

#### `execution_rule_sets`

- `id`
- `name`
- `position_base`：默认执行前总权益
- `max_symbol_position`
- `cash_buffer`
- `slippage_bps`
- `commission_rate`
- `minimum_commission`
- `stamp_tax_rate`
- `duplicate_signal_policy`
- `effective_from`

### 4.2 当前跟踪

#### `tracked_instruments`

- `id`
- `instrument_id`
- `tracking_state`：`WATCHING / HOLDING / CLOSED / EXPIRED`
- `recommended_at`
- `watch_expires_at`
- `source_recommendation_id`
- `latest_action`
- `latest_signal_at`
- `created_at / updated_at`

规则：

- `WATCHING` 超过配置天数自动转为 `EXPIRED`，页面不再展示。
- `HOLDING` 不执行时间清理。
- 买入成交后自动由 `WATCHING` 转为 `HOLDING`。
- 清仓成交后转为 `CLOSED`；是否重新进入观察由业务规则决定。

当前前端使用 5 个自然日；正式开发前建议确认是否应改为 5 个交易日，并将其做成配置。

### 4.3 信号日志

#### `signal_events`

- `id`：内部事件 ID
- `external_event_id`：上游事件 ID
- `instrument_id`
- `occurred_at`：上游信号时间
- `received_at`：本系统收到时间
- `signal_type`：B、①、④、红色信号等
- `raw_action`
- `normalized_action`：`BUY / ADD / WATCH / REDUCE / SELL`
- `target_position`
- `reference_price`
- `raw_payload_json`
- `source_name`
- `fingerprint`
- `processing_status`
- `processing_reason`
- `created_at`

唯一约束优先使用 `(source_name, external_event_id)`；没有上游 ID 时使用指纹。信号事件只新增，不直接修改或删除。解析规则变化时保存解析版本，不覆盖原始 payload。

### 4.4 模拟执行

#### `paper_orders`

- `id`
- `account_id`
- `signal_event_id`
- `side`
- `order_type`
- `requested_price`
- `requested_quantity`
- `status`
- `reject_code`
- `reject_detail`
- `rule_snapshot_json`
- `submitted_at`
- `created_at`

建议唯一约束 `(account_id, signal_event_id, execution_version)`，防止重复执行。

#### `paper_fills`

- `id`
- `order_id`
- `instrument_id`
- `filled_at`
- `price`
- `quantity`
- `commission`
- `tax`
- `slippage_amount`
- `created_at`

### 4.5 账本

#### `cash_ledger`

- `id`
- `account_id`
- `event_type`
- `amount`
- `balance_after`
- `order_id / fill_id`
- `occurred_at`

#### `position_lots`

- `id`
- `account_id`
- `instrument_id`
- `source_fill_id`
- `original_quantity`
- `remaining_quantity`
- `unit_cost`
- `available_date`

#### `positions`

- `account_id`
- `instrument_id`
- `quantity`
- `available_quantity`
- `cost_total`
- `average_cost`
- `realized_pnl`
- `updated_at`

`positions` 是当前状态快照，`position_lots` 和成交记录是可复算依据。

### 4.6 行情和估值

#### `market_daily`

- `trade_date`
- `instrument_id`
- `open / high / low / close`
- `source`
- `updated_at`

若要按信号时间判断可成交性，需要增加分钟行情表或外部行情适配器。首版可以采用“信号参考价 + 滑点立即成交”。

### 4.7 运维与审计

#### `job_runs`

- `job_type`
- `started_at / finished_at`
- `status`
- `input_count / success_count / failure_count`
- `error_detail`
- `idempotency_key`

#### `audit_events`

保存规则调整、资金调整、订单冲正、任务重放等高风险操作。

月度统计首版不单独建结果表，直接从成交与持仓查询计算；数据量上升后再增加月度快照表。

## 5. 测试桩与待定接入协议

第三方接口协议尚未确定，首版不开发信号仿真器，也不预设 HTTP 推送、轮询或文件导入方式。后端先通过测试桩验证完整业务链路。

测试桩采用固定样例数据，直接调用 `signal_service.ingest()` 等应用服务，不经过网络接口。样例仅代表内部领域对象，不作为未来第三方协议：

```json
{
  "event_id": "source-20260722-000123",
  "symbol": "300377.SZ",
  "occurred_at": "2026-07-22T09:43:06+08:00",
  "signal_type": "B",
  "action": "BUY",
  "target_position": 0.25,
  "reference_price": 13.98,
  "raw_text": "盘中出现 B 信号",
  "source": "test-stub",
  "version": 1
}
```

首批固定桩数据至少覆盖：

1. 单只股票首次出现买入信号。
2. 同一事件重复提交，用于验证幂等。
3. 同一股票连续出现多个 B 信号。
4. 持仓股票出现减仓、清仓信号。
5. 现金不足、低于一手、T+1 不可卖等拒绝场景。
6. 跨月成交，用于验证月度统计边界。

测试桩建议存放在 `tests/fixtures/`，由自动测试装载；不要在生产表中长期保留演示数据。外部协议确定后，再增加 Adapter 将第三方字段转换成当前内部领域对象。截图只作为审计附件，不作为自动交易输入。

## 6. 应用接口规划（协议确定后开放）

首版优先实现应用服务方法和自动测试。以下 HTTP 路由是候选方案，不视为已冻结的外部协议；前端仍可直接调用同进程内的应用服务。

### 当前跟踪

- `GET /api/tracking`
- `GET /api/tracking/{symbol}`
- `POST /api/tracking/{symbol}/expire`

### 信号日志

- `POST /api/signals/events`
- `POST /api/signals/events/batch`
- `GET /api/signals?symbol=&date=&signal_type=`
- `GET /api/signals/{event_id}`

### 模拟执行

- `POST /api/execution/preview/{event_id}`
- `POST /api/execution/execute/{event_id}`
- `GET /api/orders`
- `GET /api/orders/{order_id}`
- `GET /api/fills`

### 月度统计

- `GET /api/statistics/monthly?month=2026-07`
- `GET /api/statistics/monthly/{symbol}?month=2026-07`
- `GET /api/statistics/monthly/export?month=2026-07`

所有写接口支持幂等键，错误响应返回明确业务代码，如：

- `DUPLICATE_SIGNAL`
- `NO_POSITION_CHANGE`
- `INSUFFICIENT_CASH`
- `BELOW_MIN_LOT`
- `T1_AVAILABLE_INSUFFICIENT`
- `ACTION_CONFLICT`
- `MISSING_REFERENCE_PRICE`

## 7. 自动交易规则

### 买入/加仓

```text
目标市值 = 执行前账户总权益 × 目标仓位
交易差额 = 目标市值 - 当前持仓市值
模拟成交价 = 参考价 × (1 + 买入滑点)
买入数量 = floor(交易差额 / 模拟成交价 / 100) × 100
```

执行前校验：现金、现金缓冲、最大单票仓位、最小一手、信号是否已执行。

### 减仓/卖出

根据目标仓位计算目标数量，卖出量不得超过可卖数量。A 股当日买入批次在下一交易日才可卖。

### 重复信号

连续多个 B 信号全部进入信号历史，但不一定都产生订单：

- 若目标仓位未变化：记录 `NO_POSITION_CHANGE`。
- 若信号为新的更高目标仓位：只交易差额。
- 相同上游事件重复推送：按幂等键直接返回已有处理结果。

### 成本与盈亏

- 默认移动加权平均成本。
- 已实现盈亏 = 卖出净收入 - 对应持仓成本。
- 未实现盈亏 = 最新市值 - 剩余持仓成本。
- 总盈亏 = 已实现盈亏 + 未实现盈亏。

## 8. 月度统计口径

“交易股数”定义为当月发生过至少一笔模拟成交的不同股票数量，不是成交股份数量。

月度总览：

- 交易股数：`COUNT(DISTINCT instrument_id)`
- 买入次数：当月 BUY 成交笔数
- 卖出次数：当月 SELL 成交笔数
- 累计投入：当月买入成交金额 + 买入费用
- 本月盈亏：当月已实现盈亏 + 月末持仓未实现盈亏变化
- 本月收益率：本月盈亏 / 约定分母

收益率分母需业务确认。建议首版同时保存两种口径：

1. `profit / monthly_invested_amount`
2. `profit / beginning_account_equity`

股票明细按当月成交股票分组，展示买卖次数、买卖数量、投入、仓位、已实现/未实现盈亏和状态。

## 9. 后台任务

| 任务 | 频率 | 作用 |
|---|---:|---|
| 测试桩执行 | 测试时按需 | 装载固定事件，验证业务链路与幂等性 |
| 信号处理 | 实时或队列触发 | 标准化动作、执行规则、生成模拟订单 |
| 观察清理 | 每日开盘前 | 将超期 WATCHING 转为 EXPIRED |
| 行情更新 | 盘中/收盘 | 更新估值价、高低收 |
| 日终结算 | 每个交易日收盘后 | 计算持仓、权益和日收益快照 |
| 月度统计 | 查询时或月末 | 生成月度总览和股票明细 |
| 数据备份 | 每日 | 备份数据库并保留恢复点 |

所有任务写入 `job_runs`，重复运行不能重复记账。

## 10. 实施阶段

### 阶段 0：清理现有原型（1～2 天）

- [x] 移除 MANUAL 账户、人工成交、对账相关模型与服务。
- [x] 将运行时代码的 `shadow_*` 命名改为明确的 `paper_*` 或领域命名。
- [x] 引入版本化迁移机制，停止使用启动时散落的建表逻辑。
- [x] 保留 PAPER 核算测试并补充旧库迁移测试。

阶段 0 已于 2026-07-30 完成。迁移程序只保留旧库中的 PAPER 数据；
旧 `shadow_*` 表名仅存在于兼容迁移代码中，迁移完成后会被移除。

### 阶段 1：当前跟踪与信号日志（2～3 天）

- [x] 实现 `instruments`、`tracked_instruments`、`signal_events`。
- [x] 实现逐事件入库、幂等、原始 payload、股票单页信号查询。
- [x] 建立固定测试桩和 fixture，直接测试应用服务，不开发仿真器。
- [x] 实现观察超期任务和持仓不清理规则。
- [x] 将当前跟踪和信号历史前端替换为真实查询。

阶段 1 已于 2026-07-30 完成。Demo 暂按 5 个完整自然日计算观察期限：
荐股当天为第 0 天，第 5 天仍展示，从第 6 天开始标记为 `EXPIRED`。
接口协议确定后可将天数与自然日/交易日口径配置化。

### 阶段 2：自动模拟执行（3～5 天）

- 冻结信号到动作/目标仓位的映射规则。
- 实现执行预览、订单状态机、成交、费用、滑点、100 股取整和 T+1。
- 实现现金流水、持仓批次和移动加权成本。
- 实现重复信号只留痕、不重复买入。

### 阶段 3：交易统计（2～3 天）

- 实现月度总览查询。
- 实现按股票分组的月度成交统计。
- 统一已实现/未实现盈亏和月收益率口径。
- 增加 CSV/Excel 导出。

### 阶段 4：上游接入与影子运行（3～5 天）

- 与第三方共同冻结字段、鉴权、时间格式、推送/拉取方式和错误重试约定。
- 接入第三方信号 API 或文件流。
- 接入稳定行情源。
- 加入任务状态、失败重试、告警和每日备份。
- 连续使用真实数据影子运行并复核账本。

在第三方协议未确定时，可以先完成阶段 0～3，并通过测试桩验收内部业务链路；阶段 4 单独等待协议冻结。阶段 0～3 预计 8～13 个开发日，阶段 4 预计另需 3～5 个开发日。

## 11. 测试与验收

最低自动测试场景：

1. 相同事件推送两次，只保存一次信号并只执行一次。
2. 同一股票连续多个 B 信号全部留痕，但相同目标仓位不重复买入。
3. 空仓收到目标 25% 信号，按权益和 100 股规则生成正确数量。
4. 当前 12.5%，收到目标 25%，只买入仓位差额。
5. 当日买入后收到卖出信号，受 T+1 限制拒绝或部分执行。
6. 现金不足、超仓、缺价格时订单拒绝且不改变账本。
7. 买入—部分卖出—再次买入后，成本和已实现盈亏正确。
8. 成交写入失败时，订单、现金、持仓全部回滚。
9. 观察记录超过 5 天自动过期，持仓记录不清理。
10. 月度交易股数按不同股票计数，不按股份数量计数。
11. 月度汇总等于股票明细加总。
12. 每个订单均能反查信号事件和原始 payload。

## 12. 开发前需要冻结的业务问题

1. 观察 5 天是自然日还是交易日？
2. 买入、加仓、减仓、卖出分别如何映射目标仓位？
3. 连续多个相同信号在什么条件下允许再次加仓？
4. 模拟成交价使用信号参考价、下一分钟开盘价，还是参考价加滑点？
5. 上游能否提供稳定的 `external_event_id` 和精确到秒的时间？
6. 佣金、最低佣金、印花税和滑点参数是多少？
7. 月收益率分母采用月初权益、累计投入还是两种都展示？
8. 清仓后股票立即移出，还是重新进入 5 天观察期？

## 13. 当前代码处理建议

现有代码中的 PAPER 下单、成交、现金、持仓批次和 T+1 逻辑可以保留作为领域原型；以下内容与最新范围不一致，应在阶段 0 移除：

- MANUAL 账户和配对账户
- `record_manual_fill`
- `reconciliation_rows`
- 人工交易与双账本相关的未使用页面函数

前端当前使用的跟踪、信号历史和月度统计样例数据，应在阶段 1～3 逐页替换为 Application Service 返回的数据，不直接在页面中写 SQL。

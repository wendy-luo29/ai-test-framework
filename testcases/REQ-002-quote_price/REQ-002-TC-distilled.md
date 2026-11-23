# REQ-002 "少而准"测试用例设计（TC-QPS 系列）

> 需求: `requirements/docs/REQ-002_quote_price_sync.md`（V1.1，POST /quote/price_sync）
> AC 清单: `requirements/decomposition/REQ-002-AC-list.yaml`（35 个原子能力）
> 前版: `testcases/REQ-002-TC-list.xlsx`（73 条，评审 **拒绝**——超规模、双分支断言不可执行）
> 本版: **15 个测试函数 / 21 个可执行实例**，全部单分支断言，AC 100% 可追溯（覆盖或显式挂起）

## 一、设计原则

| 原则 | 落地方式 |
|---|---|
| 一个 AC 至多一条用例 | 可合并的 AC 合并进同一条主流程用例（如 AC-01/02/09/14/18/26/28 → TC-QPS-001） |
| 单分支断言（评审 M-06） | 金额一律 lsp_scp 验证 SQL 现算现比（half-up 三位）；负向统一断言 `code != "200"` + 计费任务未落库（§6 仅 200=成功，R-002 闭环前唯一可执行口径） |
| 可执行 | 数据未回填（dest_b / 无价卡承运商 / 澳邮承运商）时用例 **skip 并给出回填指引**，不误报失败 |
| 可自动化 | 全部参数化驱动；requestId/shipmentCode/packageCode/orderCode 每次构造时重新生成（时间戳+随机），重复执行不触发幂等、不产生脏数据（评审 M-13） |
| 规避未决口径 | 组包用例 SKU 全部 qty=1，规避 R-050（累加基数）歧义；内部择优断言 `金额==min(两模式现算)`，无需预知胜者，规避 M-14 |

## 二、AC → TC 追溯矩阵（35 个 AC）

### 已覆盖（22 个 AC → 15 个 TC）

| TC | 名称 | 优先级 | 覆盖 AC | 断言要点 |
|---|---|---|---|---|
| TC-QPS-001 | 主流程双承运商成功（smoke） | P0 | 01,02,09,14,18,26,28 | L1 200；L2 回显/包装/VO 契约/未启用字段 null；L3 每承运商恰 1 行、排序、isBest=1 唯一且最低、金额=SQL 现算 |
| TC-QPS-002 | 幂等重放（smoke） | P0 | 03 | 重放响应报价一致 + lsp_quote_task 计数不增（R-034 响应形态不锁） |
| TC-QPS-003 | 新 requestId 同 orderCode | P1 | 04 | 计费任务数增加（联合键不同=新请求） |
| TC-QPS-004 | zone 映射切换 | P0 | 20 | dest_a/dest_b 两 postcode 各自金额=各自 zone 段现算（dest_b 校准点3） |
| TC-QPS-005 | 多包裹求和（smoke） | P0 | 17 | 金额=Σ逐包裹现算、calcMode=1 |
| TC-QPS-006 | 续重段 >5kg | P1 | 19 | 5.1kg→6kg，fee+(w-5)×per_kg 现算比对 |
| TC-QPS-007 | 承运商内部择优 | P0 | 27 | 金额==min(一票一件现算和, 一票多件现算)，恰 1 行 |
| TC-QPS-008 | 包裹层 0 取 SKU / 组包 | P1 | 15,16 | 退化与组包（max/max/Σ/Σ+降序）后按最终箱规现算；qty=1 规避 R-050 |
| TC-QPS-009 | 超箱规承运商被过滤 | P1 | 22 | 三边和 125：受限承运商无行、另一承运商正常 |
| TC-QPS-010 | 箱规边界恰好可发 | P2 | 21 | 三边和=120、称重=22 均可发（"最长边=120"与三边和规则数学互斥，登记缺口） |
| TC-QPS-011 | PO Box 过滤 | P1 | 24,25 | check=200 邮筒地址非澳邮无行；=100 正常计算；地址用 gotcha_001 小写变体 |
| TC-QPS-012 | 无价卡承运商跳过（smoke） | P0 | 30 | data 无该行、其余正常（R-037 已闭环） |
| TC-QPS-013 | 参数校验族 | P2 | 05,07,12 | 7 个参数：4 必填缺失、承运商双空、orderCode 33 字符（拒绝）；requestId 恰 64 字符（成功+金额现算）；拒绝时任务不落库 |
| TC-QPS-014 | 主数据不存在族 | P2 | 13,32 | 推定口径（R-046）：未知承运商静默跳过；未知仓库整单失败 |
| TC-QPS-015 | 鉴权拒绝 | P1 | 35 | 无 Token 不产生计费任务；HTTP 语义挂 R-005 不锁状态码 |

### 显式挂起（13 个 AC，不进脚本）

| AC | 场景 | 挂起原因 | 责任方 |
|---|---|---|---|
| AC-06 | requestId 未传 | R-049 行为与回显口径未定 | 后端 |
| AC-08 | isPushWms/pushResultTo 组合 | R-043 默认值与组合矩阵未定 | 产品+后端 |
| AC-10 | 策略编码计费 | **H-01**: 真实 carrierStrategyCode 与 refs 数据未确认，执行必失败 | 开发 |
| AC-11 | VIR\|carrierId\|carrierId 格式 | Q-022 三段含义无解释 | 后端 |
| AC-23 | 仅一承运商超箱规错误提示 | R-027 code/msg 形态未定义 | 产品+后端 |
| AC-29 | canShipping=false 行可见性 | R-021 两处口径矛盾 | 后端 |
| AC-31 | 承运商超时整单报错 | 需故障注入/Mock，环境不具备（R-032） | 测试开发 |
| AC-33 | 多仓成功结构 | R-029 data 结构与 isBest 分布未定 | 产品+后端 |
| AC-34 | 多仓一仓失败 | R-002 失败形态未定 | 后端 |

## 三、校准点清单（跑通 db 用例前必须回填）

| # | 位置 | 内容 | 校准方法 |
|---|---|---|---|
| 1 | `config/lsp_quote/price_sync.yaml` → master_data.carrier_no_rate_id | 无有效价卡的承运商 id | lsp_carrier_rate 实查 |
| 2 | 同上 → master_data.au_post_carrier_id | 澳邮承运商 id | lsp_carrier 实查 |
| 3 | 同上 → destinations.dest_b | 与 2000 不同 zone 的目的地 | lsp_carrier_zone 按 carrier_id 实查 postcode |
| 4 | 同上 → sql.zone_rate / task_count_* | SQL 列名（zone 关联列、weight_from/weight_to、task 表粒度） | 按 lsp_scp 实际 schema 校准；zone_rate 必须返回 fee/per_kilogram_fee/fuel_rate |

运行前提：
- `config/base.yaml`: `services.lsp_quote.<env>` 指向被测环境（为空则全部 skip）；
- 环境变量 `TEST_LSP_QUOTE_TOKEN`（Bearer Token）；
- 环境变量 `TEST_DB_PASSWORD`（lsp_scp 只读密码，金额现算用例必需，缺失则 db 用例 skip）。

## 四、执行方式

```bash
pytest tests/api/test_quote_price_sync.py -v           # 全量 21 实例
pytest tests/api/test_quote_price_sync.py -m smoke -v  # 冒烟 4 条（001/002/005/012）
pytest tests/api/test_quote_price_sync.py -m "db" -v   # 仅 DB 现算用例
```

标记：`api` `module_lsp_quote` `feature_pricing` `smoke`（P0 冒烟）`db`（依赖 lsp_scp 现算）。

## 五、规模对比

| 项 | 旧版（73 条） | 本版 |
|---|---|---|
| 用例数 | 73 | 15 函数 / 21 实例（≤30/API 达标，评审 M-12） |
| 断言分支 | 6 处双分支不可执行 | 0 处，全部单分支 |
| AC 追溯 | 单行堆积不可审 | 35/35 逐条覆盖或挂起+责任方 |
| 金额期望 | 部分静态示例值 | 100% SQL 现算现比 |
| 重复执行污染 | 无清理策略 | 唯一 id 生成，天然隔离 |

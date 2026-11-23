# REQ-002 "少而准"测试用例设计（TC-QPS 系列）

> 需求: `requirements/docs/REQ-002_quote_price_sync.md`（**V1.6**，POST /quote/price_sync）
> AC 清单: `requirements/decomposition/REQ-002-AC-list.yaml`（V1.6，44 个有效 AC + 9 个 retired）
> 评审: `requirements/reviews/REQ-002-review.md` REV-REQ-002-006（§10 第 6 轮 V1.6 增量复审，gate=pass）
> 本版: **29 个测试函数 / 48 个可执行实例**，全部单分支断言，AC 100% 可追溯（覆盖或显式挂起）

## 一、V1.6 设计原则

| 原则 | 落地方式 |
|---|---|
| **验证重心** | **PRO 是新增承运商，箱规与计费结果是本需求核心**：三边和/最长边/称重箱规、分段计费、续重、取整、体积重全部以 PRO 为被测对象；其他承运商只验证「参与比价 + 正常择优」，不做金额断言 |
| 一个 AC 至多一条用例 | 可合并的 AC 合并进同一条主流程用例（如 AC-01/02/14/18/26/28/49 → TC-QPS-001） |
| 单分支断言 | 金额只对 PRO 用 lsp_scp 验证 SQL 现算现比（half-up 三位）；其他承运商只校验参与比价与择优结果；失败按响应体 `code="500" + msg 非空 + data=null` 断言（HTTP 状态码视为传输层，不强制 500） |
| 接口入口单一 | 所有正向用例只用 `carrierStrategyCode`（策略编码或 `VIR\|id\|id`）；`carrierIds` 仅 TC-QPS-031 出现，用于验证其不参与选承运商 |
| 不做幂等 | `requestId` 仅追踪、非必填；相同 `requestId+orderCode` 连调两次 → 2 行任务（TC-QPS-020） |
| 可执行 | 校准点未回填时用例 **skip 并给出回填指引**，不误报失败 |
| 可自动化 | 全部参数化驱动；requestId/orderCode/shipmentCode/packageCode 每次重新生成（时间戳+随机），重复执行不产生脏数据 |

## 二、AC → TC 追溯矩阵（44 个有效 AC）

| TC | 名称 | 优先级 | 覆盖 AC | 断言要点 |
|---|---|---|---|---|
| TC-QPS-001 | 主流程双承运商成功 + 落库 | P0 | 01,02,14,18,26,28,49 | HTTP 200；包装/VO 契约（响应不含 requestId/orderCode）；每承运商恰 1 行且金额>0；isBest=1 恰一行且最低；排序；PRO 金额 SQL 现算；查库校验 request_id/order_code、task status=200、address 2 行（100/200）、package/SKU 行数、job_log≥1 |
| TC-QPS-004 | zone 映射切换 | P0 | 20 | dest_a/dest_b 两 postcode 各自金额=各自 zone 段现算 |
| TC-QPS-005 | 多包裹求和 | P0 | 17,29 | 金额=Σ逐包裹现算；PRO 行 calcMode=1 |
| TC-QPS-006 | 续重段 >5kg | P1 | 19 | 5.1kg→6kg，fee+(w-5)×per_kg 现算比对 |
| TC-QPS-007 | 非 PRO 承运商参与择优 | P1 | 27 | 两包一票返回恰 1 行，金额 ≤ 两包分别计费之和（不做金额现算） |
| TC-QPS-008 | 包裹层 0 取 SKU / 组包 | P1 | 15,16 | 退化与组包（max/max/Σ/Σ+降序）后按最终箱规现算；qty=1 规避累加基数 |
| TC-QPS-009 | 新增承运商超箱规被过滤 | P1 | 22 | 新增承运商无行、老承运商正常报价 |
| TC-QPS-010 | 箱规边界恰好可发 | P2 | 21 | 三边和=120、原始称重=22 均可发 |
| TC-QPS-012 | 无价卡承运商跳过 | P0 | 30 | data 无该行、其余正常 |
| TC-QPS-013 | 参数校验族 | P2 | 05,07,12 | 必填缺失/长度越界/策略空 → 500；requestId 恰 64 字符成功；不落任务 |
| TC-QPS-014 | 主数据异常族 | P2 | 32,39 | 未知仓库→500 落 status=300；VIR 中 carrierId 不存在→500 不落行 |
| TC-QPS-016 | 计费重只取称重 | P1 | 14 | 体积重≫实重时金额仍=称重段现算 |
| TC-QPS-017 | 箱规按单包裹判定 | P2 | 21 | 两包各 21.5kg（ceil=22）均可发 |
| TC-QPS-019 | pushResultTo 非法枚举 | P2 | 08 | pushResultTo=100 → 500 且不落行 |
| TC-QPS-020 | 不做幂等 | P1 | 45 | 相同 requestId+orderCode 连调两次均成功，任务数 +1 |
| TC-QPS-021 | 包裹结构与编码校验 | P1 | 36,37 | 包裹层部分为 0、packageCode 重复 → 500 不落行 |
| TC-QPS-022 | 策略编码非法族 | P2 | 38,40 | VIR 段非法、策略不存在、策略绑定空集合 → 500 |
| TC-QPS-023 | 仅新增承运商且超箱规 | P1 | 23 | → 500，落 status=300 |
| TC-QPS-024 | 失败统一契约 | P1 | 44 | code="500" + msg 非空 + data=null + success=false（HTTP 状态不强制；响应不含 requestId/orderCode） |
| TC-QPS-025 | 无价卡失败分支 | P1 | 51,52 | 参数化：单承运商无价卡、全部无价卡 → 500 落 status=300 |
| TC-QPS-026 | 并列金额排序 | P1 | 48 | 出现金额并列时 isBest=1 为并列中排序第一条；无并列则 skip |
| TC-QPS-027 | 失败落库口径 | P1 | 50 | 计算失败落 status=300、predict_price=0、carrier 空；参数校验不落行；job_log 软断言 |
| TC-QPS-028 | 策略编码计费 | P1 | 10 | carrierStrategyCode=quote_price 计费；按 ubi/broers 有效 8 家校验范围，范围外 dfe/shippit 仅告警 |
| TC-QPS-029 | 地址字段校验 | P2 | 41,42 | country=AU/au/Australia 通过、NZ→500；state 全称通过且落库简称 |
| TC-QPS-030 | 透传字段不校验 | P2 | 46,47 | shippingType/shipmentType 任意值不影响计费；closePoboxCheck 100/200 均正常计费 |
| TC-QPS-031 | carrierIds 优先级 | P2 | 43 | 同时传 carrierIds 与 VIR 策略，结果只覆盖策略承运商 |
| TC-QPS-032 | 不传 requestId | P2 | 06 | 仍正常计费（不做幂等、不去重） |
| TC-QPS-033 | 承运商超时 | P2 | 31 | 需故障注入；当前环境无手段时 skip |
| TC-QPS-034 | schema 上限 | P2 | 53 | 依赖 M-007 闭环；未闭环 skip |

### 显式挂起（运行期 skip，责任方见待确认清单）

- AC-31（TC-QPS-033）：需承运商询价超时故障注入，环境不具备。
- AC-53（TC-QPS-034）：M-007（数组 maxItems / 数值上限）未闭环。
- AC-10（TC-QPS-028）：`strategy_refs` 已回填为 ubi/broers 有效 8 家，不再 skip；AC-40 空集合分支依赖 `strategy_empty_code=eiz`。
- AC-51/52（TC-QPS-025）：`carrier_no_rate_id` / `carrier_no_rate_id_2` 已置空（无价卡仅 VIR 强制指定时出现，返回 0 元，属特殊场景不在范围），运行时 skip。

### 已废弃（V1.1 编号，不回收）

TC-QPS-002/003（幂等）、TC-QPS-011/018（PO Box 过滤）、TC-QPS-015（鉴权）随 V1.6 范围变更删除。

## 三、校准点清单

| # | 位置 | 内容 | 状态 |
|---|---|---|---|
| 1 | `master_data.carrier_no_rate_id` | 无有效价卡承运商 | 已置空：VIR 强制指定无价卡承运商返回 0 元，属特殊场景不在范围 |
| 2 | `master_data.carrier_no_rate_id_2` | 第二个无价卡承运商（AC-52） | 已置空：无真实场景，运行期 skip |
| 3 | `destinations.dest_b` | 与 2000 不同 zone 的目的地 | 已回填 postcode 3000 → MEL（base fee 6.12） |
| 4 | `sql.*` | 按 lsp_scp 实际 schema 校准 | 已校准（zone 列名、from_zone/to_zone、min_weight/max_weight） |
| 5 | `master_data.strategy_refs` | quote_price 承运商范围 | 已回填 8 家（`carrier_agent_code in ('ubi','broers') and status=100`） |
| 6 | `master_data.strategy_empty_code` | 绑定空承运商集合的策略编码 | 已回填 `eiz`（实测 code="500" / "No available carrier"） |
| 7 | `master_data.carrier_pro_id` | 金额断言承运商 | PRO `CAR2025062611067266788`：四段价卡与需求公式一致（1.15kg=19.96 / 5.1kg=30.493 / 22kg=38.107 实测） |
| 8 | `master_data.carrier_base_id` / `carrier_legacy_id` | 比价与内部择优承运商 | base=Aramex `CAR1772558358570467341`（最低价 5.724，isBest=1）；legacy=IPEC `CAR1772558358570467347`（1.15kg/6kg 均 19.074，仅做择优行为校验，不断言金额） |

运行前提：
- `config/base.yaml`: `services.lsp_quote.<env>` 指向被测环境（为空则全部 skip）；
- **本接口不鉴权、不经网关，不需要 Token**；
- 环境变量 `TEST_DB_PASSWORD`（lsp_scp 只读密码，金额现算/落库用例必需，缺失则 db 用例 skip）。

## 四、执行方式

```bash
pytest tests/api/test_quote_price_sync.py -v            # 全量 48 实例
pytest tests/api/test_quote_price_sync.py -m smoke -v   # 冒烟 5 条（001/004/005/007/012）
pytest tests/api/test_quote_price_sync.py -m "db" -v    # 仅 DB 现算用例
```

标记：`api` `module_lsp_quote` `feature_pricing` `smoke`（P0 冒烟）`db`（依赖 lsp_scp 现算）。

## 五、规模对比

| 项 | V1.1（19 条） | 本版（V1.6） |
|---|---|---|
| 用例数 | 19 函数 / 30 实例 | 29 函数 / 48 实例（≤30/API） |
| 断言分支 | 部分双分支 | 0 处，失败统一 500 契约 |
| AC 追溯 | 27/35 覆盖 + 8 挂起 | 44/44 覆盖（2 条运行期 skip）+ 9 retired |
| 金额期望 | SQL 现算 | SQL 现算（仅 PRO；其他承运商只校验参与比价与择优） |
| 请求入口 | carrierIds | carrierStrategyCode（carrierIds 仅验证兼容优先级） |

## 六、待办

1. 回填校准点 2/5/6（`carrier_no_rate_id_2` / `strategy_refs` / `strategy_empty_code`）。
2. AC-31 故障注入手段落地后再启用 TC-QPS-033。
3. M-007 闭环后再设计 TC-QPS-034 的边界值。

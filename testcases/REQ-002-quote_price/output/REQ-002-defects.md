# REQ-002 /quote/price_sync 缺陷清单（需求为主口径）

> 需求基准：`requirements/docs/REQ-002_quote_price_sync.md`（V1.6）
> AC 基准：`requirements/decomposition/REQ-002-AC-list.yaml`（44 有效 AC）
> 判定口径（2026-11-23 用户确认）：**需求为主，差异提缺陷**。用例断言按需求写死，实现差异不在用例中放宽；HTTP 状态码视为传输层，失败以响应体 `code` 判定。
> 环境：dev `http://192.168.1.71:13100`；查询库 `lsp_scp`。实测日期 2026-11-23。
> 响应契约：同步响应**不返回** `requestId`/`orderCode`（业务方 2026-11-23 确认），需按入参查 `lsp_quote_task` 校验，不记为缺陷。

| 编号 | 严重度 | 关联 AC | 缺陷描述 | 需求期望 | 实测证据 | 复现 |
|---|---|---|---|---|---|---|
| D-01 | 高 | AC-05/AC-07/AC-12/AC-44 | 失败响应 `code` 不稳定：必填缺失与 orderCode 超 32 字符返回 `"400"`，`carrierStrategyCode` 为空返回 `null` | §6/AC-44 要求失败统一 `code="500"` + msg 非空 + data=null | 必填缺失实测 `code="400"`；orderCode=33 字符实测 `code="400"`；策略为空实测 `code='null'`；无可用承运商（eiz）与策略空集合返回 `"500"` 符合 | `pytest ... -k "test_request_validation or test_failure_contract"` |
| D-02 | 中 | AC-36 | 包裹层尺寸/重量**部分为 0** 仍返回成功并计费 | 需求要求 HTTP 500、不落任务行 | 包裹 `length=30, width=0` 请求成功返回报价 | `pytest ... -k test_package_validation` |
| D-03 | 中 | AC-37 | 同一请求 `packageCode` 重复仍成功，且运费按重复包裹翻倍 | 需求要求 500、不落任务行 | 两个包裹同 `packageCode` 返回成功，金额=2 倍单价 | `pytest ... -k test_package_validation` |
| D-04 | 中 | AC-08 | `pushResultTo=100` 非法枚举未被拒绝 | 需求要求非法枚举 500 | 实测返回成功报价 | `pytest ... -k test_invalid_push_result_to` |
| D-05 | 中 | AC-40 | 非法策略编码（`VIR\|`、`NO_SUCH_STRATEGY`）请求超时不返回 | 需求要求失败快速返回并落 status=300 | 实测 >30s 未返回（`ReadTimeout`），任务停留在 `status=100`（进行中），requestId 如 `SAC17954331872027909` | 手工以 `carrierStrategyCode=NON_EXIST_CODE` 调接口后查 `lsp_quote_task` |
| D-06 | 低 | AC-47 | `closePoboxCheck=200` + PO Box 地址时返回 `code="500"`（No available carrier），而 `closePoboxCheck=100` 正常 | PO Box 过滤已移出本接口，100/200 均应正常计费（仅透传） | 同一 payload 仅切换 `closePoboxCheck`：100 → 成功 2 行；200 → `data=null`、`code="500"` | `pytest ... -k "test_passthrough_fields and pobox"` |
| D-07 | 中 | AC-43 | 同时传 `carrierIds` 与 `carrierStrategyCode` 时，**carrierIds 仍优先生效**，返回 carrierIds 指定的承运商 | Q-014/C-15：接口层只认 `carrierStrategyCode`，`carrierIds` 仅兼容保留不参与选承运商 | 双向实测均以 carrierIds 为准：`VIR\|PRO` + carrierIds=[Aramex] → 返回 Aramex；`VIR\|Aramex` + carrierIds=[PRO] → 返回 PRO | `pytest ... -k test_carrier_ids_ignored` |
| D-08 | 中 | AC-32 | 未知仓库 `WH-NOT-EXIST-0000` 未按计费失败处理，仍返回成功报价（Aramex 5.724） | C-04：未知仓库按计费失败处理（落 status=300 行 + job_log 原因） | requestId=`SAC17954331295155049` 实测 `code="200"`、`data` 1 行；落库 `status=200` | `pytest ... -k "test_master_data_missing and unknown-warehouse"` |
| D-09 | 中 | AC-39 | VIR 中携带不存在的 carrierId（`CAR-NOT-EXIST-000000`）被静默忽略，仍返回其余有效承运商报价 | Q-014：VIR 段 carrierId 不存在应返回 500 | requestId=`SAC17954331326055123` 实测 `code="200"`、返回 Aramex 5.724；落库 `status=200` | `pytest ... -k "test_master_data_missing and unknown-carrier"` |

## 范围说明（非缺陷）

- `carrierStrategyCode=quote_price` 运行期返回 12 家承运商，其中 4 家为 `dfe`（CAR1772558358570467350）与 `shippit`（CAR1770625562872602651/650/653），超出本次指定的 `carrier_agent_code in ('ubi','broers') and status=100` 范围。策略本身绑定 4 个 agent（broers/dfe/shippit/ubi），故该现象属策略配置事实；TC-QPS-028 仅对 ubi/broers 8 家做范围校验，范围外行告警并排除比价。
- 无价卡承运商仅能通过 VIR 强制指定构造，实测返回成功 + `shippingCost=0.0`（requestId=`SAC1795430195700726`），属人为绕过策略过滤的特殊场景，不纳入用例与缺陷。

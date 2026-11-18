---
requirement_id: REQ-002
review_id: REV-REQ-002-001
reviewer: 需求评审（review-requirements）
review_date: 2026-11-18
target: requirements/docs/REQ-002_quote_price_sync.md
source_spec: requirements/specs/lsp_quote/quote_price/all.v1.0.0.json
input_mode: B-1
gate: reject
blocking_count: 4
next_action: 回退 requirement-enrichment 补齐 R-001 ~ R-004 后复审
---

# REQ-002 需求评审记录 — 承运商运费计算同步接口

## 1. 评审对象与结论摘要

| 项 | 内容 |
|---|---|
| 评审对象 | `POST /quote/price_sync` 承运商运费计算同步接口 |
| 需求文档 | `requirements/docs/REQ-002_quote_price_sync.md` |
| 接口快照 | `requirements/specs/lsp_quote/quote_price/all.v1.0.0.json`（OpenAPI 3.0.1，1 个 path，7 个 schema） |
| 上游待确认清单 | `requirements/changes/REQ-002-pending.md`（M 14 项 / Q 21 项） |
| 评审方法 | 结构盘点 + 逻辑闭环 / 边界异常 / 数据一致性 / 可测试性 四维破坏性审查 |
| 问题数量 | 高 11、中 9、低 2，共 22 项 |
| 门禁结论 | **[拒绝 Reject]**，4 个阻塞项未闭环 |

## 2. 结构盘点

| 检查项 | 结果 | 证据 |
|---|---|---|
| 必填字段 | 不通过 | `QuoteTaskDto.required` = ownerId / orderCode / shipTo / warehouse，缺 `carrierStrategyCode`（描述含 `@NotBlank`）；`requestBody` 未声明 `required: true` |
| 命名风格 | 部分通过 | 请求响应均为 camelCase，无 snake_case 混用；响应存在 `tc` / `tp` / `hasMore` 无含义缩写（见 R-017） |
| 基础设施 | 不通过 | `servers: []`、`security: []`；无 `example` / `examples`；`responses` 仅 200 且 `description` 为空 |
| 枚举值 | 不通过 | `pushResultTo` 的 `enum` 为空数组；`shippingType` / `closePoboxCheck` / `calcMode` / `isBest` 无 `enum` |
| 错误定义 | 不通过 | `components.responses` 与 `components.securitySchemes` 均为空对象 |
| 文档元信息 | 不通过 | `info.description` 为 "Lsp Backend API Documentation"，`tags` 为 `test/*`，`info.version=1.0` 是文档版本而非接口版本 |

## 3. 漏洞清单

### 3.1 高级（不解决无法设计用例或断言必然出错）

| 编号 | 级别 | 位置 | 问题 | 修改建议 | 责任方 |
|---|---|---|---|---|---|
| R-001 | 高 | §1 接口概览、§7 业务规则 | 业务背景、调用方、使用场景、调用链路缺失，正文只能用"推测"表述 | 补「业务背景与使用场景」：触发时机、上游系统、下游动作、是否与申报/推送联动；确认后删除对应"推测" | 产品 |
| R-002 | 高 | §6 错误码 | 错误码表为空，响应只定义 200，异常场景无预期结果 | 至少覆盖 6 类：缺少必填字段、`carrierStrategyCode` 格式错误、策略不存在/已禁用、承运商询价超时、无可承运承运商、推送失败；每行补 HTTP 状态 / code / message / 触发条件 | 后端 |
| R-003 | 高 | §7 业务规则 | 计费公式、比价择优、PO Box 检查、地址校验规则全部缺失，主流程金额无法计算 | 改为规则表（规则ID / 名称 / 输入 / 判定 / 输出 / 异常），至少含体积重系数来源、计费重取值、附加费项、比价排序、PO Box 命中处理 | 产品 + 后端 |
| R-004 | 高 | §3.2 报价项 | 全部金额字段无币种、精度、是否含税；`shippingCostWithTax` 无税率来源 | 每个金额字段补「币种 / 精度 / 含税口径 / 取整规则」；补税率来源（系统配置还是按国家/州） | 产品 + 后端 |
| R-005 | 高 | §2.2 `carrierStrategyCode` | 描述含 `@NotBlank`，但 `required` 数组未列，必填用例预期不确定 | 以注解为准：`required` 加入 `carrierStrategyCode`，文档必填列写"是（注解强制）" | 后端 |
| R-006 | 高 | §2.2 `pushResultTo` | `enum: []` 空数组与描述 0/100/200/300 冲突，合法值/非法值用例无法判定 | 删除空 `enum` 或补 `[0,100,200,300]`，并写明其他取值是否报错、报什么 | 后端 |
| R-007 | 高 | §3.2 报价项 | 响应不回显 `requestId` / `orderCode`；`data` 无排序规则、无报价唯一标识 | 响应包装加 `requestId` / `orderCode` 回显；`data` 写明排序规则；补报价唯一键供定位 | 后端 |
| R-008 | 高 | §2.2 `carrierStrategyCode` / `carrierIds` | 两字段是二选一、可并用还是有优先级，均未定义 | 补参数组合矩阵：只传 A / 只传 B / 都传 / 都不传，各自结果与错误码 | 产品 + 后端 |
| R-009 | 高 | §1 接口概览、§2.1 请求头 | 无环境地址、无鉴权方式，鉴权与越权用例无法设计 | 补 dev / staging / prod 地址、鉴权方式与 Token 获取路径、是否需租户或追踪头 | 后端 + 运维 |
| R-010 | 高 | §2.2 `requestId` | 未声明是否幂等，重复提交预期未知 | 明确同 `requestId` 重复提交时：返回首次结果 / 重新计算 / 报错，以及标识保留时长 | 产品 + 后端 |
| R-011 | 高 | §3.2 `canShipping` | `canShipping=false` 时金额字段返回 null / 0 / 缺失未定义；不可承运的承运商是否仍返回未定义 | 写明 false 时各字段取值，以及该条记录是否保留在 `data` 中 | 产品 + 后端 |

### 3.2 中级（可写用例但存在歧义）

| 编号 | 级别 | 位置 | 问题 | 修改建议 | 责任方 |
|---|---|---|---|---|---|
| R-012 | 中 | §2.2 `closePoboxCheck` | 描述称默认 200，schema 无 `default`；100/200 语义需确认 | schema 补 `default: 200` 与 `enum: [100,200]`，文档默认值列填 200 | 后端 |
| R-013 | 中 | §2.2 `shippingType` / `shipmentType` | `shippingType` 描述列 100/200/300/600 缺 400/500；`shipmentType` 是 string 且无取值清单 | 补 `shippingType` 完整枚举；给出 `shipmentType` 合法取值或改为枚举类型 | 产品 |
| R-014 | 中 | §2.2 ~ §2.6 | 字符串长度、数组上限（`warehouse` / `packages` / `items`）、数值上限缺失，边界用例无上限可测 | 数组补 `maxItems`，字符串补 `maxLength`，数值补 `maximum` | 后端 |
| R-015 | 中 | §2.2 `bookingOrderId` | "申报运费计费时要传"判定条件模糊，不传时的行为未定义 | 写清触发条件与不传时的行为（忽略 / 报错 / 走默认） | 产品 |
| R-016 | 中 | §2.6 `cube` / `cubeWeight` | 同时出现在请求与计费逻辑中，无法判断是入参还是系统计算值 | 明确二者为入参（需校验）还是系统计算（请求中忽略） | 后端 |
| R-017 | 中 | §3.1 响应包装 | `tc` / `tp` / `hasMore` 含义未知；同步接口出现 `hasMore` 不合理 | 补三字段含义；若同步返回全量则删除 `hasMore` | 后端 |
| R-018 | 中 | §3.2 `isBest` / `choiceShippingCost` | 比价规则未定义，`isBest` 含义未知，默认值 2 出现在响应中不合理 | 明确 1/2 含义、比价口径（是否含税、是否含附加费）；移除响应字段的 `default` | 产品 |
| R-019 | 中 | §9 依赖与数据影响 | 承运商询价依赖外部系统、`isPushWms` 推送副作用不可观测，缺 Mock 与降级约定 | 写明外部依赖、超时降级策略、推送结果的可查询途径（日志 / 查询接口 / 消息） | 后端 |
| R-020 | 中 | §2.3 `country` | 传国家代码还是全称、是否只支持 AU 未定义 | 明确取值格式（建议 ISO 两位码）与支持范围 | 产品 |

### 3.3 低级（不影响主流程）

| 编号 | 级别 | 位置 | 问题 | 修改建议 | 责任方 |
|---|---|---|---|---|---|
| R-021 | 低 | §1 接口概览 | 调用方、调用频率为推测内容，影响回归范围判断 | 补调用方与触发频率，或删除这两行 | 产品 |
| R-022 | 低 | §1 / §10 | `tags` 为 `test/*` 前缀；`info.version=1.0` 是文档版本；变更记录为空 | 改正式分组，补接口版本号与首条变更记录 | 后端 |

## 4. 进入下一步前必须澄清清单

| 编号 | 问题 | 责任方 | 阻塞的用例类型 |
|---|---|---|---|
| R-001 | 业务背景与调用链路不明 | 产品 | 正常流程边界、验收口径 |
| R-002 | 无错误码与错误响应 | 后端 | 全部异常用例 |
| R-003 | 计费、比价、PO Box、地址校验规则缺失 | 产品 + 后端 | 主流程金额断言、附加费、PO Box |
| R-004 | 金额币种 / 精度 / 税口径缺失 | 产品 + 后端 | 全部金额断言 |
| R-005 | `carrierStrategyCode` 必填冲突 | 后端 | 必填校验 |
| R-006 | `pushResultTo` 枚举与描述冲突 | 后端 | 枚举合法值 / 非法值 |
| R-007 | 响应无回显、无排序、无唯一标识 | 后端 | 结果归属断言、最优项定位 |
| R-008 | 策略编码与 `carrierIds` 关系不明 | 产品 + 后端 | 参数组合矩阵 |
| R-009 | 无环境地址与鉴权方式 | 后端 + 运维 | 鉴权、越权、连通性 |
| R-010 | 幂等未定义 | 产品 + 后端 | 重复提交 |
| R-011 | 不可承运分支返回形态未定义 | 产品 + 后端 | `canShipping=false` 分支 |
| R-012 ~ R-020 | 见漏洞清单 | 产品 / 后端 | 默认值、枚举覆盖、边界值、依赖与副作用 |

## 5. 具体修改内容

### 5.1 §2.2 请求体：修必填与枚举（对应 R-005、R-006）

现状：`carrierStrategyCode` 不在 `required`；`pushResultTo` 的 `enum` 是空数组。

改为：

```json
"required": ["ownerId", "orderCode", "carrierStrategyCode", "shipTo", "warehouse"]
```

```json
"pushResultTo": {
  "type": "integer",
  "description": "设置结果推送：0 不推送 | 100 SCP | 200 WMS | 300 ERP",
  "enum": [0, 100, 200, 300],
  "default": 100
}
```

文档 §2.2 对应两行改为：

| 字段 | 类型 | 必填 | 约束 | 默认值 | 说明 |
|---|---|---|---|---|---|
| carrierStrategyCode | string | 是 | 规则：`VIR\|carrierId\|carrierId` | — | 物流策略编码 |
| pushResultTo | integer | 否 | 0 不推送 \| 100 SCP \| 200 WMS \| 300 ERP | 100 | 设置结果推送 |

### 5.2 §6 错误码：先定覆盖范围，code 待后端填（对应 R-002）

| HTTP | code | message | 触发条件 | 处理建议 |
|---|---|---|---|---|
| 400 | 待填 | 待填 | `ownerId` / `orderCode` / `shipTo` / `warehouse` 缺失 | 修正请求后重试 |
| 400 | 待填 | 待填 | `carrierStrategyCode` 格式不符合 `VIR\|carrierId\|carrierId` | 从策略列表接口重新获取 |
| 400 | 待填 | 待填 | 策略不存在或已禁用 | 更换策略编码 |
| 200 / 504 | 待填 | 待填 | 承运商询价超时 | 重试或减少承运商范围 |
| 200 | 待填 | 待填 | 所有承运商均不可承运 | 检查地址与包裹信息 |
| 200 | 待填 | 待填 | 推送 SCP / WMS / ERP 失败 | 人工补偿或重新推送 |

> 注意：`code` 是 HTTP 状态码还是响应体 `code` 字段，需要同时写明（见 R-017、Q-002）。

### 5.3 §3.2 报价项：补回显、排序与唯一标识（对应 R-007）

建议在 `RestResultListQuotePriceSyncVo` 增加：

| 字段 | 类型 | 说明 |
|---|---|---|
| requestId | string | 回显请求 ID，用于断言结果归属 |
| orderCode | string | 回显订单号 |

并补充：`data` 排序规则（建议 `isBest=1` 优先，其次 `shippingCost` 升序，需产品确认）；若同一承运商可能返回多条，需补报价唯一键。

### 5.4 §3.2 金额与不可承运分支（对应 R-004、R-011）

金额表头改为带口径的形式：

| 字段 | 类型 | 说明 |
|---|---|---|
| shippingCost | number | 运费，币种待确认（业务为澳洲地址，推测 AUD），2 位小数，不含税 |
| shippingCostWithTax | number | 含税运费，税率来源待确认（国家 / 州 / 系统配置） |
| surcharge | number | 附加费，构成项（偏远 / 燃油 / 其他）待确认 |
| choiceShippingCost | number | 比价运费，比价口径（是否含税、是否含附加费）待确认 |

补充一段：`canShipping=false` 时 `shippingCost` / `choiceShippingCost` / `shippingCostWithTax` / `surcharge` 返回 null（而不是 0），该条记录保留/不保留在 `data` 中（待产品确认）。

### 5.5 §7 业务规则：从叙述改成规则表（对应 R-003）

| 规则ID | 规则名 | 输入 | 判定 / 计算 | 输出 | 异常 |
|---|---|---|---|---|---|
| RULE-01 | 策略解析 | `carrierStrategyCode` / `carrierIds` | 待补：二选一还是并集、优先级 | 承运商候选集 | 无候选时报错 |
| RULE-02 | 计费重计算 | 包裹长宽高、SKU 重量、体积重系数 | 待补：按承运商取系数、取实际重与体积重较大者、保留小数位 | 计费重 | 缺尺寸或重量 |
| RULE-03 | 运费计算 | 计费重、价格表 | 待补：首重/续重、分区、附加费叠加顺序 | `shippingCost` | 无价卡 |
| RULE-04 | 比价择优 | 各承运商报价 | 待补：比价口径、并列时如何取最优 | `isBest`、`choiceShippingCost` | 无可比报价 |
| RULE-05 | PO Box 与地址校验 | `closePoboxCheck`、地址字段 | 待补：命中 PO Box 的处理、地址校验失败是否跳过该承运商 | `canShipping`、`remark` | — |
| RULE-06 | 结果推送 | `isPushWms`、`pushResultTo` | 待补：推送时机、失败重试、与计算是否同事务 | 推送结果 | 推送失败 |

原有 5 步"推测流程"在规则表补齐后删除，避免两套描述并存。

### 5.6 §1 与 §8：补基础设施与非功能（对应 R-009、R-010）

| 项 | 需补内容 |
|---|---|
| 环境地址 | dev / staging / prod 三个 base URL |
| 鉴权方式 | Token 类型与获取路径、是否需租户头 / 追踪头 |
| 幂等 | 同 `requestId` 重复提交的行为与标识保留时长 |
| 超时 | 确认 §8 中"基础 30s / Carrier A 20s / Carrier B 15s"是否适用于本接口 |
| 限流 | 阈值与触发后的返回 |

### 5.7 §2.2 参数组合矩阵（对应 R-008）

| carrierStrategyCode | carrierIds | 预期结果 | 状态 |
|---|---|---|---|
| 传 | 不传 | 待确认 | 待产品 |
| 不传 | 传 | 待确认 | 待产品 |
| 传 | 传 | 待确认（是否取交集/并集/以策略为准） | 待产品 |
| 不传 | 不传 | 待确认（报错还是取默认策略） | 待产品 |

## 6. 门禁结论

**[拒绝 Reject]**

- 阻塞项 4 个：R-001（业务背景）、R-002（错误码）、R-003（业务规则）、R-004（金额口径）。
- 高级未闭环：11 项；中级未闭环：9 项。
- 允许：回退 `requirement-enrichment` 补充文档，产品 / 后端按第 4、5 节确认并改写。
- 禁止：进入 `split-requirements` 与 `design-testcases`；禁止写 `knowledge/rules/`。
- 复审条件：R-001 ~ R-011 全部闭环后重新评审，更新 front-matter 的 `gate` / `blocking_count` / `next_action` 并追加复审记录。

## 7. 复审记录

| 轮次 | 日期 | 结论 | 已闭环 | 仍阻塞 |
|---|---|---|---|---|
| 1 | 2026-11-18 | 拒绝 | — | R-001 ~ R-022 |

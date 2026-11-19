---
requirement_id: REQ-002
source: Apifox 导出 OpenAPI 3.0.1（LspQuote / QuoteTaskController）
original_file: requirements/specs/lsp_quote/quote_price/all.v1.0.0.json
input_mode: B-1
archived_at: 2026-11-18
owner: wendy-luo29
---

# 承运商运费计算同步接口（POST /quote/price_sync）

## 1. 接口概览

| 项 | 内容 |
|---|---|
| 接口名称 | 承运商运费计算同步接口 |
| 请求方法 | POST |
| 接口路径 | `/quote/price_sync` |
| 接口说明 | 按订单与包裹信息返回各承运商的运费报价列表 |
| 接口分组 | `test/LspQuote/quote-task-controller/QuoteTaskController` |
| 请求类型 | `application/json` |
| 响应类型 | `application/json` |
| 鉴权方式 | Bearer Token 鉴权 |
| 幂等说明 | `requestId` 作为请求唯一标识，当requestId+orderCode联合唯一时为新请求，否则为重复，直接查询上一次请求结果 |
| 调用方 | ERP 下单或运费试算流程 |
| 调用频率 | 随订单量触发 |

## 2. 请求定义

### 2.1 请求头

| 字段 | 必填 | 说明 |
|---|---|---|
| Content-Type | 是 | `application/json` |

### 2.2 请求体（QuoteTaskDto）

| 字段 | 类型 | 必填 | 约束 | 默认值 | 说明 |
|---|---|---|---|---|---|
| requestId | string | 否 | **max 64**（DB `lsp_quote_task.request_id varchar(64)`） | — | 请求唯一 ID |
| ownerId | string | 是 | **max 32**（DB `owner_id varchar(32)` NOT NULL） | — | 归属人 ID |
| orderCode | string | 是 | 最大长度 32（JSON + DB `order_code varchar(32)` 一致） | — | ERP 销售订单号 |
| carrierStrategyCode | string | 条件必填 | **DB `carrier_strategy_code TEXT` 无硬长度上限**；与 `carrierIds` 不能同时为空；取值两种形式：① 指定策略编码 ② 指定承运商 `VIR\|carrierId\|carrierId` | — | 物流策略编码 |
| carrierIds | array\<string\> | 条件必填 | **每项 max 32**（DB `lsp_carrier.id varchar(32)`） | — | 承运商 ID 数组；与 `carrierStrategyCode` 不能同时为空 |
| shipmentType | string | 否 | **max 32**（DB `shipment_type varchar(32)`） | — | 计费流水号分类 |
| shipTo | object | 是 | 见 2.3 | — | 派件地信息 |
| warehouse | array\<object\> | 是 | 见 2.4 | — | 发件地信息 |
| isPushWms | boolean | 否 | — | — | 是否推送结果到终端；为 `true` 时按 `pushResultTo` 推送 |
| pushResultTo | integer | 否 | 0 不推送 \| 100 SCP \| 200 WMS \| 300 ERP；**接口直调场景传 0**，100/200/300 仅业务流程链路使用 | 100 | 设置结果推送 |
| shippingType | integer | 否 | 100 发货单 \| 200 退货单 \| 300 手工单 \| 600 其他单 | 100 | 发货单类型 |
| closePoboxCheck | integer | 否 | 100 关闭 \| 200 不关闭 | 200 | 是否关闭 PO Box 检查 |
| bookingOrderId | string | 否 | 申报运费计费时传入（仅业务流程链路触发；接口级测试不覆盖该分支） | — | 申报单号 |

### 2.3 派件地址（shipTo / QuoteTaskAddressDto）

> DB 映射：`lsp_quote_task_address`（type=派件方向）

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| country | string | 是 | **max 32**（DB `country varchar(32)` NOT NULL） | 国家（国家代码或名称） |
| state | string | 是 | **max 32**（DB `state varchar(32)` NOT NULL） | 州 / 省 |
| suburb | string | 是 | **max 255**（DB `suburb varchar(255)` NOT NULL） | 城区 |
| postcode | string | 是 | **max 32**（DB `postcode varchar(32)` NOT NULL） | 邮编 |
| address1 | string | 是 | **max 255**（DB `address1 varchar(255)` NOT NULL） | 地址第一行 |
| address2 | string | 否 | **max 255**（DB `address2 varchar(255)` NOT NULL DEFAULT=''，接口可空） | 地址第二行 |

### 2.4 发件地（warehouse[] / QuoteTaskWarehouseDto）

> 发件地有两层含义：① 仓库编码引用 `lsp_warehouse.code`（已建好的仓库主数据）；② 发件地址快照（同 shipTo 结构）。DB 侧 `lsp_quote_task` 只存 `warehouse_code`，地址字段不入库。

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| warehouseCode | string | 是 | **max 50**（DB `lsp_warehouse.code varchar(50)`） | 仓库编码（引用 `lsp_warehouse` 主数据） |
| shipmentCode | string | 是 | **max 64**（DB `lsp_quote_task.shipment_code varchar(64)` NOT NULL） | 发货单号 |
| country | string | 是 | **max 32**（同 shipTo） | 国家（发件地快照，非 DB 强约束） |
| state | string | 是 | **max 32**（同 shipTo） | 州 / 省 |
| suburb | string | 是 | **max 255**（同 shipTo） | 城区 |
| postcode | string | 是 | **max 32**（同 shipTo） | 邮编 |
| address1 | string | 是 | **max 255**（同 shipTo） | 地址第一行 |
| address2 | string | 否 | **max 255**（同 shipTo） | 地址第二行 |
| packages | array\<object\> | 是 | 见 2.5 | 该仓库发出的包裹 |

### 2.5 包裹（packages[] / QuoteTaskPackageDto）

> DB 映射：`lsp_quote_task_package`

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| packageCode | string | 是 | **max 32**（DB `package_code varchar(32)` NOT NULL） | 包裹编码 |
| items | array\<object\> | 是 | 见 2.6 | 包裹内 SKU 明细 |
| length | number | 否 | **DB 精度 `double(12,3)`**，默认 0（DB DEFAULT=0.000） | 包裹长度；缺省时系统取 SKU 汇总或自动组包 |
| width | number | 否 | **DB 精度 `double(12,3)`**，默认 0 | 包裹宽度 |
| height | number | 否 | **DB 精度 `double(12,3)`**，默认 0 | 包裹高度 |
| weight | number | 否 | **DB 精度 `double(12,3)`**，默认 0 | 包裹重量 |

### 2.6 包裹内明细（items[] / QuoteTaskPackageSkuDto）

> DB 映射：`lsp_quote_task_package_sku`

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| sku | string | 是 | **max 40**（DB `sku varchar(40)` NOT NULL） | SKU 编码 |
| qty | integer | 是 | 最小 1（JSON schema）；**DB `smallint` NOT NULL** | 数量 |
| length | number | 是 | 最小 0.01；**DB 精度 `double(12,3)`** | SKU 长度 |
| width | number | 是 | 最小 0.01；**DB 精度 `double(12,3)`** | SKU 宽度 |
| height | number | 是 | 最小 0.01；**DB 精度 `double(12,3)`** | SKU 高度 |
| weight | number | 是 | 最小 0.01；**DB 精度 `double(12,3)`** | SKU 重量 |
| cube | number | 否 | **DB 精度 `double(12,3)` NOT NULL** | 体积，填写，落库由系统计算 |
| cubeWeight | number | 否 | **DB 精度 `double(12,3)` NOT NULL** | 体积重，填写，落库由系统计算 |

## 3. 响应定义

### 3.1 响应包装（RestResultListQuotePriceSyncVo）

| 字段 | 类型 | 说明 |
|---|---|---|
| **requestId** | **string** | **请求唯一 ID（与请求入参回显一致）；DB 映射 `lsp_quote_task.request_id`** |
| **orderCode** | **string** | **ERP 销售订单号（与请求入参回显一致）；DB 映射 `lsp_quote_task.order_code`** |
| data | array\<QuotePriceSyncVo\> | 报价结果列表,排序：isBest=1 优先，其他按 `shippingCost` 升序 |
| code | string | 业务状态码 |
| msg | string | 提示信息 |
| tc | integer(int64) | 耗时或时间戳 |
| tp | integer | — |
| hasMore | integer | 是否还有更多结果（推测，同步接口为何存在待确认） |
| success | boolean | 是否成功 |

> **为什么 requestId / orderCode 放在包装层而不是 data[] 里**：这两个是**请求级**标识，同一次请求的所有报价行都属于同一个 requestId + orderCode。放在 data[] 每条里是冗余的。报价行的唯一标识见 §3.2。

### 3.2 报价项（QuotePriceSyncVo）

> DB 映射：承运商主数据来自 `lsp_carrier` + `lsp_carrier_agent` + `lsp_carrier_channel`；计算结果对应 `lsp_quote_task_` / `lsp_quote_task_job_log`；**无独立的 QuotePriceSyncVo 落库表**。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| calcMode | integer | — | 计算方式：1=一票一件；2=一票多件（DB `lsp_quote_task_job.calc_mode smallint`） |
| canShipping | boolean | — | 是否可承运。承运商价卡会同时计算一票一件和一票多件；若承运商仅支持一票一件，一票多件结果标记为 false，比价时跳过该计算方式 |
| agentCode | string | — | **max 255**（DB `lsp_carrier_agent.code varchar(255)` NOT NULL） |
| agentName | string | — | **max 128**（DB `lsp_carrier_agent.name varchar(128)` NOT NULL） |
| channelCode | string | — | **max 255**（DB `lsp_carrier_channel.code varchar(255)` NOT NULL） |
| channelName | string | — | **max 128**（DB `lsp_carrier_channel.name varchar(128)` NOT NULL） |
| carrierCode | string | — | **max 255**（DB `lsp_carrier.code varchar(255)` NOT NULL） |
| carrierName | string | — | **max 128**（DB `lsp_carrier.name varchar(128)` NOT NULL） |
| bookingCarrierId | string | — | **max 32**（DB `lsp_carrier.id varchar(32)` NOT NULL） |
| bookingCarrierCode | string | — | 下游申报使用的唯一编码（同 carrierCode） |
| bookingCarrierCalc | string | — | 申报承运商的申报方式：1=一票一件；2=一票多件（DB 无直接映射，运行时决定） |
| remark | string | — | 备注 |
| shippingCost | number | — | 比价择优的运费，精度：四舍五入保留三位小数；**DB `predict_price decimal(12,3)`** |
| choiceShippingCost | number | — | （暂未启用，返回 null） |
| shippingCostWithTax | number | — | 含税运费（暂未启用） |
| surcharge | number | — | 附加费（暂未启用，返回 null；**本轮新增承运商 AU.TGE.PRIORITY.PRO 无 RAS 类附加费**） |
| closePoboxCheck | integer | — | 关闭 PO Box 过滤：100=关闭；200 或为空=不关闭（DB `lsp_quote_task.close_pobox_check smallint`） |
| isBest | integer | 2 | 最优标记：见 §7 择优规则；1=全局最优（最终运费），2=内部最优（承运商内部一票一件 vs 一票多件择优） |

> **报价行唯一标识**（用于定位具体一条报价、断言归属）：
> - 包装级唯一键：`requestId + orderCode`（§3.1 回显，所有 data[] 行共享）
> - 行级唯一键：`bookingCarrierId + calcMode`（同一承运商同一 calcMode 只有一条 isBest=2 的内部最优行）
> - 在同一个包装内，**不会出现** `bookingCarrierId` 相同的多条 data[] 行（两层择优后每承运商只保留内部最优）

## 4. 请求示例

> 场景：BG03 仓库（Melbourne VIC 3012）发 2.3kg SKU 到 Sydney NSW 2000，同时询价 AU.TGE.PRIORITY.PRO + AU.TGE.PRIORITY 两个承运商。仓库、地址、承运商 ID 均来自 `lsp_scp` 库真实数据。

```json
{
  "requestId": "SAC202611190001",
  "ownerId": "BG",
  "orderCode": "TESTSO20261119-001",
  "carrierIds": [
    "CAR2025062611067266788",
    "CAR1772558358570467346"
  ],
  "shipTo": {
    "country": "AU",
    "state": "NSW",
    "suburb": "Haymarket",
    "postcode": "2000",
    "address1": "456 George Street",
    "address2": ""
  },
  "warehouse": [
    {
      "warehouseCode": "BG03",
      "shipmentCode": "TESTBG0320261119-001",
      "country": "AU",
      "state": "VIC",
      "suburb": "Maidstone",
      "postcode": "3012",
      "address1": "C 35-77 Emu Road",
      "packages": [
        {
          "packageCode": "QTP38177618321238-001",
          "items": [
            {
              "sku": "SKU-WIDGET-AU-001",
              "qty": 2,
              "length": 15.0,
              "width": 10.0,
              "height": 8.0,
              "weight": 1.15,
              "cube": 1200.0,
              "cubeWeight": 0.0
            }
          ],
          "length": 30.0,
          "width": 20.0,
          "height": 15.0,
          "weight": 2.3
        }
      ]
    }
  ],
  "isPushWms": false,
  "pushResultTo": 0,
  "shippingType": 100,
  "closePoboxCheck": 200
}
```

**示例说明**（与 DB 校验）：

| 项 | 值 | DB 依据 |
|---|---|---|
| 仓库 BG03 | `warehouse_code=BG03`, `address1="C 35-77 Emu Road"`, `state=VIC`, `postcode=3012` | `lsp_warehouse` 表 |
| 派件地址 | `suburb_name="haymarket"`, `postcode=2000`, `state_code=NSW` | `lsp_address_suburb_postcode` 表 |
| 承运商 ID | PRO=`CAR2025062611067266788` / 非 PRO=`CAR1772558358570467346` | `lsp_carrier.id` |
| 箱规 | 30×20×15cm，三边之和 65cm ≤ 120cm，称重 2.3kg ≤ 22kg | 通过箱规校验 |
| calcMode | 只有 1 个包裹 1 种 SKU，calcMode=1（一票一件）和 calcMode=2（一票多件）结果相同 | — |

## 5. 响应示例

> 两个承运商同时询价的两层择优结果。重量 2.3kg → 向上取整 3kg；zone 映射：MEL → ADL（需按 carrier_zone 表映射；派件地址 suburb+state+postcode 对应的 zone 为 lsp_carrier_zone 数据库实查值，非按目的城市名称推断），对应价卡段均为 `1.001 ≤ w ≤ 3.0`。
>
> **计费公式**：`shippingCost = fee × (1 + fuel_rate)`，四舍五入保留三位小数。DB 里存在的 `extra_fee` 列当前不参与计算，也无 RAS 类附加费（详见 §7 附加费规则）。

| 承运商 | fee | fuel_rate | 计算 | shippingCost | 层次 |
|---|---|---|---|---|---|
| AU.TGE.PRIORITY | 7.87 | 0.097 | 7.87 × 1.097 | **8.633** | isBest=1 ✅ 全局最优 |
| AU.TGE.PRIORITY.PRO | 15.52 | 0.2861 | 15.52 × 1.2861 | **19.960** | isBest=2（内部最优） |

```json
{
  "requestId": "SAC202611190001",
  "orderCode": "TESTSO20261119-001",
  "code": "200",
  "msg": "success",
  "success": true,
  "tc": 1200,
  "tp": 0,
  "hasMore": 0,
  "data": [
    {
      "calcMode": 1,
      "canShipping": true,
      "agentCode": "ubi",
      "agentName": "UBI",
      "channelCode": "toll",
      "channelName": "Team Global Express",
      "carrierCode": "AU.TGE.PRIORITY",
      "carrierName": "UBI Team Global Express Priority",
      "bookingCarrierId": "CAR1772558358570467346",
      "bookingCarrierCode": "AU.TGE.PRIORITY",
      "bookingCarrierCalc": "1",
      "remark": "MEL->ADL / 1.001~3.0kg / fee=7.87 extra=5.0 fuel=0.097",
      "shippingCost": 8.633,
      "choiceShippingCost": null,
      "shippingCostWithTax": null,
      "surcharge": null,
      "closePoboxCheck": 200,
      "isBest": 1
    },
    {
      "calcMode": 1,
      "canShipping": true,
      "agentCode": "ubi",
      "agentName": "UBI",
      "channelCode": "toll",
      "channelName": "Team Global Express",
      "carrierCode": "AU.TGE.PRIORITY.PRO",
      "carrierName": "UBI Team Global Express Priority",
      "bookingCarrierId": "CAR2025062611067266788",
      "bookingCarrierCode": "AU.TGE.PRIORITY.PRO",
      "bookingCarrierCalc": "1",
      "remark": "MEL->ADL / 1.001~3.0kg / fee=15.52 extra=5.0 fuel=0.2861",
      "shippingCost": 19.960,
      "choiceShippingCost": null,
      "shippingCostWithTax": null,
      "surcharge": null,
      "closePoboxCheck": 200,
      "isBest": 2
    }
  ]
}
```

### 两层择优过程

```
请求输入     各承运商内部择优           全局择优后 data
─────────   ──────────────────         ────────────────
Carrier A   calcMode=1  $8.633  ←最优 → isBest=1  全局最低
Carrier A   calcMode=2  $8.633  (同1)   (合并为内部最优)
Carrier B   calcMode=1  $19.960  ←最优 → isBest=2  内部最优但全局第二
Carrier B   calcMode=2  $19.960  (同1)   (合并为内部最优)
```

> 当某承运商 `canShipping=false`（如一票多件超箱规）时，该 calcMode 不参与本承运商内部择优；承运商若无有效 calcMode 结果则整体不出现。

## 6. 错误码

| code | message | 触发条件 | 处理建议 |
|---|---|---|---|
| 200 |  | 计算成功，返回择优结果和其他承运商计算明细 |  |
| 500 |  | 计算失败/超时/无价卡/找不到发运地址 |  |

## 7. 业务规则

### 流程

1. 接收上游订单、发件仓与包裹 / SKU 明细。
2. 按 `carrierStrategyCode` 选策略或指定承运商 ID：① 指定策略（如 `quote_price`）② 指定承运商（格式 `VIR|carrierId|carrierId`）；与 `carrierIds` 不能同时为空。
3. 逐个承运商计算运费，返回报价数组。
4. 按 `address1` / `address2` 检查 PO Box：`closePoboxCheck=200` 时邮筒地址只走澳邮；为 `null` 或 `100` 时按策略与指定承运商计算。
5. 承运商比价择优规则（`choiceShippingCost` / `shippingCostWithTax` / `surcharge` 暂未启用，均返回 null）
   - **第一层：承运商内部择优** — 每个承运商同时计算 calcMode=1（一票一件）和 calcMode=2（一票多件），取两者 `shippingCost` 较低者，标记为该承运商的**内部最优**（isBest=2）。若某承运商仅支持其中一种 calcMode，直接取该模式结果。
   - **第二层：全局择优** — 所有承运商的内部最优集合中，取 `shippingCost` 最低者标记为**全局最优**（isBest=1），即最终运费值。
   - `canShipping=false` 的计算方式不参与本承运商内部择优；该承运商若无有效计算结果则整体返回 null。
6. 按 `isPushWms`、`pushResultTo` 推送至 SCP / WMS / ERP。

### 计算规则

- **发运重**：取称重计算 `weight`，有小数向上取整；优先包裹层，无则取 SKU 层。
- **金额精度**：所有金额字段四舍五入保留三位小数；**币种暂不考虑**。
- **包裹的箱规取值计算**：支持多包裹计算，多个包裹的话按一个包裹一个包裹计算，最后运费按包裹运费之和
	- 若包裹层为0，则取sku的箱规信息；如果一个包裹存在多个sku，需要把sku的信息重新组包
		- 组包规则：
			- 取长边：对比所有 SKU，取最大的长度作为最终长边
			- 取宽边：对比所有 SKU，取最大的宽度作为最终宽边
			- 累加高：将所有 SKU 的高度进行累加求和
			- 累加重：将所有 SKU 的重量进行累加求和
			- 重排序：将最终得到的“长、宽、高”三个维度，按从大到小的顺序重新排列，拼接上总重量，得出最终箱规
- **箱规限制（不可发）**：最长边 >120cm，三边之和 >120cm，称重 >22kg。
- **总运费（税前）** = 基础运费 ×（1 + 燃油费率）
  - 称重 ≤5kg：基础运费 = `lsp_carrier_rate.fee`（Basic 首重基础运费）
  - 称重 >5kg：基础运费 = `lsp_carrier_rate.fee + (称重-5) × lsp_carrier_rate.per_kilogram_fee`（Per KG 续重单价）
  - **附加费规则**（重要）：
    1. DB `lsp_carrier_rate.extra_fee` 列当前**不参与运费计算**（所有承运商价卡里都有该字段值，但系统未使用）
    2. 当前无 RAS 类（按地区触发的偏远附加费）等其他附加费项
    3. 本轮新增承运商 AU.TGE.PRIORITY.PRO 同样无任何附加费
    4. 未来若开启 RAS 或启用 extra_fee 列，需要同步更新公式和文档
  - 燃油费率 = `lsp_carrier_rate.fuel_rate`（按承运商区分，**AU.TGE.PRIORITY.PRO 的 fuel_rate=0.2861**）
  - **zone 映射**：派件地址 postcode → zone 编码，查 `lsp_carrier_zone` 表；不同承运商 zone 划分不一样
- **择优**：两层择优，见 §7 流程第 5 步。
  - 多个承运商参与计费，如果其中一个承运商超时则整单报错；若其中一个承运商无价卡则不返回此承运商计费信息，只选择有返回结果的承运商比价
  - 多仓计费，按仓生成计费任务，按仓库计费择优，若其中一个仓计费失败，则整单计费失败
  - 若多个承运商计费，新增承运商超过箱规，直接过滤不参与计算；若仅新增承运商计费，超过箱规则给出错误提示
- **含税金额**（暂未启用）：shippingCost × 1.1；目前没有参与业务逻辑


## 8. 非功能约束

| 项 | 值 | 说明 |
|---|---|---|
| 超时 |  30s| nacos配置，现在设置的是30s超时 |
| 重试 | — | 单接口不考虑，这个业务流程调用的时候需要考虑 |
| 限流 | — | 不考虑 |
| 并发 | — | 不考虑 |
| 容量上限 | — | 单次最大承运商数 / 包裹数 / SKU 数未说明 |


## 9. 数据影响

| 数据库表名 | 说明 |
| :--- | :--- |
| `lsp_carrier` (承运商表) | 承运商基础配置表 |
| `lsp_carrier_strategy` (策略表) | 承运商策略表 |
| `lsp_carrier_strategy_refs` (关联表) | 承运商策略关联的承运商id或者代表费 |
| `lsp_carrier_rate` (价卡表) | 承运商价卡表 |
| `lsp_carrier_zone` (收件地址表) | 收件地址表 |
| `lsp_warehouse` (发货地址表) | 仓库信息表 |
| `lsp_quote` (计费结果表) | 计费结果及择优 |
| lsp_quote_task_address (计费地址表) | 计费后发货地址和收件地址信息 |
| lsp_quote_task_package（计费包裹表） | 计费包裹信息 |
| lsp_quote_task_package_sku（计费包裹的sku表） | 包裹内sku明细 |
| `lsp_quote_task_log` (计费日志表) | 参与计算的承运商及计费报错日志查看 |


## 10. 依赖影响

| 类型 | 内容 | 说明 |
|---|---|---|
| 下游服务 | 各承运商询价接口；SCP / WMS / ERP（推送） |  |
| 消息事件 | — | — |
| 副作用 | `isPushWms=true` 时可能写库或发送消息 |  |

## 10. 变更记录

| 版本 | 日期 | 变更点 | 影响范围 |
|---|---|---|---|
| V1.1 | 2026-11-18 | 新增承运商价卡计费：ubi-toll-AU.TGE.PRIORITY.PRO |1. 新增承运商价卡计费<br>2. 比价择优加入新的承运商比价 |

---
requirement_id: REQ-002
source: Apifox 导出 OpenAPI 3.0.1（LspQuote / QuoteTaskController）
original_file: requirements/specs/lsp_quote/quote_price/all.v1.0.0.json
input_mode: B-1
archived_at: 2026-11-18
owner: wendy-luo29
---

# 承运商运费计算同步接口（POST /quote/price_sync）

> 标注「推测」的内容为依据字段命名或结构推断，需审核确认或修改。
> `—` 表示无法推断，待补充；补充与确认事项见 `requirements/changes/REQ-002-pending.md`。

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
| 鉴权方式 | 未声明（`security` 为空） |
| 幂等说明 | `requestId` 作为请求唯一标识，用于幂等与链路追踪 |
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
| requestId | string | 否 | — | — | 请求唯一ID |
| ownerId | string | 是 | — | — | 归属人 ID |
| orderCode | string | 是 | 最大长度 32 | — | ERP 销售订单号 |
| carrierStrategyCode | string | 是 | 物流策略编码，可从策略列表接口获得，也可传数组 ID 集合；规则：`VIR\|carrierId\|carrierId` | — | 物流策略编码；必填依据为字段上的 `@NotBlank` |
| carrierIds | array\<string\> | 否 | — | — | 承运商 ID 数组 |
| shipmentType | string | 否 | — | — | 计费流水号分类，用于区分计费场景 |
| shipTo | object | 是 | 见 2.3 | — | 派件地信息 |
| warehouse | array\<object\> | 是 | 见 2.4 | — | 发件地信息 |
| isPushWms | boolean | 否 | 与 `pushResultTo` 关联使用 | — | 是否推送结果到终端；为 `true` 时按 `pushResultTo` 推送 |
| pushResultTo | integer | 否 | 0 不推送 \| 100 SCP \| 200 WMS \| 300 ERP | 100 | 设置结果推送 |
| shippingType | integer | 否 | 100 发货单 \| 200 退货单 \| 300 手工单 \| 600 其他单 | 100 | 发货单类型 |
| closePoboxCheck | integer | 否 | 100 关闭 \| 200 不关闭 | 200 | 是否关闭 PO Box 检查 |
| bookingOrderId | string | 否 | 申报运费计费时传入 | — | 申报单号 |

### 2.3 派件地址（shipTo / QuoteTaskAddressDto）

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| country | string | 是 | 兼容大小写及全称 | 国家（国家代码或名称） |
| state | string | 是 |兼容大小写及全称 | 州 / 省 |
| suburb | string | 是 | 兼容大小写 | 城区 |
| postcode | string | 是 | — | 邮编 |
| address1 | string | 是 | — | 地址第一行 |
| address2 | string | 否 | — | 地址第二行 |

### 2.4 发件地（warehouse[] / QuoteTaskWarehouseDto）

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| warehouseCode | string | 是 | — | 仓库编码 |
| shipmentCode | string | 是 | — | 发货单号 |
| country | string | 是 | — | 国家 |
| state | string | 是 | — | 州 / 省 |
| suburb | string | 是 | — | 城区 |
| postcode | string | 是 | — | 邮编 |
| address1 | string | 是 | — | 地址第一行 |
| address2 | string | 否 | — | 地址第二行 |
| packages | array\<object\> | 是 | 见 2.5 | 该仓库发出的包裹 |

### 2.5 包裹（packages[] / QuoteTaskPackageDto）

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| packageCode | string | 是 | — | 包裹编码 |
| items | array\<object\> | 是 | 见 2.6 | 包裹内 SKU 明细 |
| length | number | 否 | — | 包裹长度 |
| width | number | 否 | — | 包裹宽度 |
| height | number | 否 | — | 包裹高度 |
| weight | number | 否 | — | 包裹重量 |

### 2.6 包裹内明细（items[] / QuoteTaskPackageSkuDto）

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| sku | string | 是 | — | SKU 编码 |
| qty | integer | 是 | 最小 1 | 数量 |
| length | number | 是 | 最小 0.01 | SKU 长度 |
| width | number | 是 | 最小 0.01 | SKU 宽度 |
| height | number | 是 | 最小 0.01 | SKU 高度 |
| weight | number | 是 | 最小 0.01 | SKU 重量 |
| cube | number | 否 | — | 体积，填写，落库由系统计算 |
| cubeWeight | number | 否 | — | 体积重，填写，落库由系统计算 |

## 3. 响应定义

### 3.1 响应包装（RestResultListQuotePriceSyncVo）

| 字段 | 类型 | 说明 |
|---|---|---|
| data | array\<QuotePriceSyncVo\> | 报价结果列表 |
| code | string | 业务状态码 |
| msg | string | 提示信息 |
| tc | integer(int64) | 耗时或时间戳 |
| tp | integer | — |
| hasMore | integer | 是否还有更多结果（推测，同步接口为何存在待确认） |
| success | boolean | 是否成功 |

### 3.2 报价项（QuotePriceSyncVo）

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| calcMode | integer | — | 计算方式：1：一票一件；2：一票多件 |
| canShipping | boolean | — | 是否可承运 |
| agentCode | string | — | 代理编码 |
| agentName | string | — | 代理名称 |
| channelCode | string | — | 渠道编码 |
| channelName | string | — | 渠道名称 |
| carrierCode | string | — | 承运商编码 |
| carrierName | string | — | 承运商名称 |
| bookingCarrierId | string | — | 下游申报使用的承运商 ID |
| bookingCarrierCode | string | — | 下游申报使用的唯一编码 |
| bookingCarrierCalc | string | — | 申报承运商的申报方式：1：一票一件；2一票多件 |
| remark | string | — | 备注 |
| shippingCost | number | — | 运费|
| choiceShippingCost | number | — | 比价择优运费 |
| shippingCostWithTax | number | — | 含税运费 |
| surcharge | number | — | 附加费 |
| closePoboxCheck | integer | — | 关闭 PO Box 过滤：100：关闭；200或为空：不关闭 |
| isBest | integer | 2 | 是否最优；1=最优、2=非最优 |

## 4. 请求示例

> 结构示例，由 schema 生成，占位值需按实际业务替换。

```json
{
  "requestId": "<string>",
  "ownerId": "<string>",
  "orderCode": "<max 32 chars>",
  "carrierStrategyCode": "VIR|carrierId|carrierId",
  "carrierIds": ["<carrierId>"],
  "shipmentType": "<string>",
  "shipTo": {
    "country": "<string>",
    "state": "<string>",
    "suburb": "<string>",
    "postcode": "<string>",
    "address1": "<string>",
    "address2": "<string>"
  },
  "warehouse": [
    {
      "warehouseCode": "<string>",
      "shipmentCode": "<string>",
      "country": "<string>",
      "state": "<string>",
      "suburb": "<string>",
      "postcode": "<string>",
      "address1": "<string>",
      "address2": "<string>",
      "packages": [
        {
          "packageCode": "<string>",
          "items": [
            {
              "sku": "<string>",
              "qty": 1,
              "length": 0.01,
              "width": 0.01,
              "height": 0.01,
              "weight": 0.01,
              "cube": 0,
              "cubeWeight": 0
            }
          ],
          "length": 0,
          "width": 0,
          "height": 0,
          "weight": 0
        }
      ]
    }
  ],
  "isPushWms": true,
  "pushResultTo": 100,
  "shippingType": 100,
  "closePoboxCheck": 200,
  "bookingOrderId": "<string>"
}
```

## 5. 响应示例

> 结构示例，由 schema 生成，占位值需按实际业务替换。

```json
{
  "data": [
    {
      "calcMode": 0,
      "canShipping": true,
      "agentCode": "<string>",
      "agentName": "<string>",
      "channelCode": "<string>",
      "channelName": "<string>",
      "carrierCode": "<string>",
      "carrierName": "<string>",
      "bookingCarrierId": "<string>",
      "bookingCarrierCode": "<string>",
      "bookingCarrierCalc": "<string>",
      "remark": "<string>",
      "shippingCost": 0,
      "choiceShippingCost": 0,
      "shippingCostWithTax": 0,
      "surcharge": 0,
      "closePoboxCheck": 200,
      "isBest": 2
    }
  ],
  "code": "<string>",
  "msg": "<string>",
  "tc": 0,
  "tp": 0,
  "hasMore": 0,
  "success": true
}
```

## 6. 错误码

| code | message | 触发条件 | 处理建议 |
|---|---|---|---|
| 200 |  | 计算成功，返回择优结果和其他承运商计算明细 |  |
| 500 |  | 计算失败/超时/地址不可发运/无价卡/找不到发运地址 |  |

## 7. 业务规则

### 流程

1. 接收上游订单、发件仓与包裹 / SKU 明细。
2. 按 `carrierStrategyCode` 选策略或指定承运商 ID，格式 `VAR|CAR2025062611067266788`。
3. 逐个承运商计算运费，返回报价数组。
4. 按 `address1` / `address2` 检查 PO Box：`closePoboxCheck=200` 时邮筒地址只走澳邮；为 `null` 或 `100` 时按策略与指定承运商计算。
5. 按比价结果标记 `isBest`、`choiceShippingCost`。
6. 按 `isPushWms`、`pushResultTo` 推送至 SCP / WMS / ERP。

### 计算规则

- **发运重**：取 `weight`，有小数向上取整；优先包裹层，无则取 SKU 层。
- **箱规**：最长边 ≤120，三边之和 ≤120，称重 ≤22。
- **总运费（税前）** =（基础运费 + 附加费）×（1 + 燃油费率）
  - 称重 ≤5kg：基础运费 = `Basic`
  - 称重 >5kg：基础运费 = `Basic + (称重-5) × Per KG`
- **择优**：全部参与承运商中取运费最低者为最优。

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

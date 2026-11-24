# REQ-002 缺陷汇总（共 9 条）

> 生成时间：2026-11-24 16:05｜同一需求的确认缺陷合并记录于本文件。

## 缺陷一览

| 缺陷编号 | 标题 | 严重度 / 优先级 | 状态 | 关联 AC | 关联用例 |
|---|---|---|---|---|---|
| BUG-REQ002-D01 | 失败响应 code 不稳定：必填缺失/字段超长返回 400、策略为空返回 null，未统一 500 | 高 / P1 | 新建 | AC-44（关联 AC-05/AC-07/AC-12） | TC-QPS-013、TC-QPS-036、TC-QPS-037、TC-QPS-027 |
| BUG-REQ002-D02 | 包裹层尺寸部分为 0 仍成功计费（需求要求拒绝） | 中 / P2 | 新建 | AC-36 | TC-QPS-021 |
| BUG-REQ002-D03 | 同一请求 packageCode 重复仍成功，运费按重复包裹翻倍 | 中 / P2 | 新建 | AC-37 | TC-QPS-021 |
| BUG-REQ002-D04 | pushResultTo=100 非法枚举未被拒绝，仍成功计费 | 中 / P2 | 新建 | AC-08 | TC-QPS-019 |
| BUG-REQ002-D05 | 非法策略编码（VIR|、不存在的策略）请求超时不返回，任务停留 status=100 | 中 / P2 | 新建 | AC-40 | TC-QPS-022 |
| BUG-REQ002-D07 | 同时传 carrierIds 与 carrierStrategyCode 时 carrierIds 仍优先生效 | 中 / P2 | 新建 | AC-43 | TC-QPS-031 |
| BUG-REQ002-D08 | 未知仓库 WH-NOT-EXIST-0000 未按计费失败处理，仍返回成功报价 | 中 / P2 | 新建 | AC-32 | TC-QPS-014 |
| BUG-REQ002-D09 | VIR 携带不存在的 carrierId 被静默忽略，仍返回有效承运商报价 | 中 / P2 | 新建 | AC-39 | TC-QPS-014 |
| BUG-REQ002-D10 | orderCode=32 字符（需求上界）落库追加 6 位序号后超 varchar(32) 列宽 | 中 / P2 | 新建 | AC-07 | TC-QPS-035 |

---

# [BUG-REQ002-D01] 失败响应 code 不稳定：必填缺失/字段超长返回 400、策略为空返回 null，未统一 500

| 字段 | 内容 |
|---|---|
| 缺陷编号 | BUG-REQ002-D01 |
| 状态 | 新建 |
| 严重度 / 优先级 | 高 / P1 |
| 发现版本 | dev 环境当前版本（2026-11-23 实测，2026-11-24 回归仍在） |
| 提交人 / 时间 | wendy / 2026-11-24 |
| 关联需求 | REQ-002 承运商运费计算同步（/quote/price_sync） |

## 1. 环境
- 环境：dev
- Base URL：http://192.168.1.71:13100
- 部署版本：未填写

## 2. 地址
- 方法：POST
- 路径：/quote/price_sync
- 完整 URL：http://192.168.1.71:13100/quote/price_sync

## 3. 请求传参
```json
{
  "requestId": "SAC17954331872020001",
  "orderCode": "TESTSO20261123001",
  "carrierStrategyCode": "VIR|CAR2025062611067266788|CAR1772558358570467346",
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
      "shipmentCode": "TS20261123001",
      "packages": [
        {
          "packageCode": "QTP20261123001",
          "length": 30,
          "width": 20,
          "height": 15,
          "weight": 1.15,
          "items": [
            {
              "sku": "SKU-001",
              "qty": 1,
              "length": 30,
              "width": 20,
              "height": 15,
              "weight": 1.15
            }
          ]
        }
      ]
    }
  ],
  "isPushWms": 200,
  "pushResultTo": 200,
  "closePoboxCheck": 200
}
```
- Headers：Content-Type: application/json
- 复现命令：`未填写`

## 4. 返回结果
- HTTP 状态：HTTP 400（部分场景 200，按响应体 code 判定）
- 耗时：未记录
- 响应体：
```json
{
  "code": "400",
  "msg": "（实测返回业务码 400，非需求要求的 500；完整报文见 reports/report.html 对应用例）",
  "success": false,
  "data": null
}
```
- request-id：无
- 日志：无

## 5. 预期结果
- 引用 AC：AC-44（关联 AC-05/AC-07/AC-12）
- 需求原文：需求 §6/AC-44：失败统一返回 code="500" + msg 非空 + data=null；HTTP 状态码视为传输层
- 实际 vs 预期：必填缺失实测 code="400"；orderCode=33 字符实测 code="400"；策略为空实测 code=null，与需求统一 500 不符

## 6. 关联用例
| case_id | 用例标题 | AC | 优先级 | 来源 |
|---|---|---|---|---|
| TC-QPS-013 | 契约-必填校验：逐个移除 17 个必填字段（参数化 17 条，全部 xfail） | AC-44/AC-05 | P1 | tests/api/test_quote_price_sync.py |
| TC-QPS-036 | 契约-长度校验：各字段超上界 1 字符（参数化 14 条，全部 xfail） | AC-07/AC-44 | P1 | tests/api/test_quote_price_sync.py |
| TC-QPS-037 | 契约-类型校验：packages 传对象（返回 HTTP 400 默认错误体，无 500 包装层） | AC-44 | P2 | tests/api/test_quote_price_sync.py |
| TC-QPS-027 | 异常与落库：参数校验失败不落任务行（断言失败契约分支 xfail） | AC-44/AC-50 | P2 | tests/api/test_quote_price_sync.py |

## 7. 附件
- 无

## 8. 原因分析
- 现象：参数校验失败与业务失败的响应 code 各不相同：400、null、500 混用
- 直接原因：参数校验分支（必填/长度/类型）未走统一异常处理器，返回 Spring 默认 400 或业务码 400；策略编码为空分支返回 code=null
- 根本原因：失败出口未收敛到统一响应契约（code="500"+msg+data=null）：校验层、策略解析层、计费层各自拼装错误响应
- 证据：REQ-002-defects.md D-01（2026-11-23 实测）；2026-11-24 回归 33 条相关用例 xfail 证实仍在（reports/junit_quote_price_sync.xml）
- 待确认：无

## 9. 影响范围
- 受影响范围：所有失败场景的调用方无法按统一契约判断失败原因；下游按 code==500 判失败会漏判 400/null 分支
- 是否偶现：稳定复现
- 关联功能：无

## 10. 修复建议 / 验证建议
- 建议：后端增加全局异常处理器，将参数校验失败与业务失败统一包装为 code="500" + msg 非空 + data=null
- 回归范围：TC-QPS-013/019/027/035/036/037 全量回归

---

# [BUG-REQ002-D02] 包裹层尺寸部分为 0 仍成功计费（需求要求拒绝）

| 字段 | 内容 |
|---|---|
| 缺陷编号 | BUG-REQ002-D02 |
| 状态 | 新建 |
| 严重度 / 优先级 | 中 / P2 |
| 发现版本 | dev 环境当前版本（2026-11-23 实测，2026-11-24 回归仍在） |
| 提交人 / 时间 | wendy / 2026-11-24 |
| 关联需求 | REQ-002 承运商运费计算同步（/quote/price_sync） |

## 1. 环境
- 环境：dev
- Base URL：http://192.168.1.71:13100
- 部署版本：未填写

## 2. 地址
- 方法：POST
- 路径：/quote/price_sync
- 完整 URL：http://192.168.1.71:13100/quote/price_sync

## 3. 请求传参
```json
{
  "requestId": "SAC17954331872020002",
  "orderCode": "TESTSO20261123002",
  "ownerId": "BG",
  "carrierStrategyCode": "VIR|CAR2025062611067266788",
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
      "shipmentCode": "TS20261123002",
      "packages": [
        {
          "packageCode": "QTP20261123002",
          "length": 30,
          "width": 0,
          "height": 15,
          "weight": 3,
          "items": [
            {
              "sku": "SKU-001",
              "qty": 1,
              "length": 30,
              "width": 0,
              "height": 15,
              "weight": 3
            }
          ]
        }
      ]
    }
  ],
  "isPushWms": 200,
  "pushResultTo": 200,
  "closePoboxCheck": 200
}
```
- Headers：Content-Type: application/json
- 复现命令：`未填写`

## 4. 返回结果
- HTTP 状态：HTTP 200
- 耗时：未记录
- 响应体：
```json
{
  "code": "200",
  "msg": "success",
  "success": true,
  "data": [
    {
      "shippingCost": 30.018,
      "bookingCarrierId": "CAR2025062611067266788"
    }
  ]
}
```
- request-id：无
- 日志：无

## 5. 预期结果
- 引用 AC：AC-36
- 需求原文：需求 AC-36：包裹层尺寸/重量部分为 0 应被拒绝（失败返回 + 不落任务行）
- 实际 vs 预期：width=0 请求成功返回报价（data 1 行），未拒绝

## 6. 关联用例
| case_id | 用例标题 | AC | 优先级 | 来源 |
|---|---|---|---|---|
| TC-QPS-021 | 契约-结构校验：包裹尺寸部分为 0（参数化 partial-zero 条目） | AC-36 | P2 | tests/api/test_quote_price_sync.py |

## 7. 附件
- 无

## 8. 原因分析
- 现象：packages[0].width=0 仍返回成功报价
- 直接原因：包裹尺寸校验只拦截全 0/缺失，未把部分为 0 判为非法值
- 根本原因：箱规计算将 0 当作合法输入参与体积/计费流程，缺少"尺寸必须为正数"的逐项校验
- 证据：REQ-002-defects.md D-02（2026-11-23 实测）；2026-11-24 回归 xfail 证实仍在（reports/junit_quote_price_sync.xml）
- 待确认：无

## 9. 影响范围
- 受影响范围：非法包裹数据可进入计费并产生错误报价，可能误导下单决策
- 是否偶现：稳定复现
- 关联功能：无

## 10. 修复建议 / 验证建议
- 建议：包裹层与 SKU 层尺寸/重量增加逐项正数校验，任一为 0 按参数校验失败统一拒绝
- 回归范围：TC-QPS-021 全量回归

---

# [BUG-REQ002-D03] 同一请求 packageCode 重复仍成功，运费按重复包裹翻倍

| 字段 | 内容 |
|---|---|
| 缺陷编号 | BUG-REQ002-D03 |
| 状态 | 新建 |
| 严重度 / 优先级 | 中 / P2 |
| 发现版本 | dev 环境当前版本（2026-11-23 实测，2026-11-24 回归仍在） |
| 提交人 / 时间 | wendy / 2026-11-24 |
| 关联需求 | REQ-002 承运商运费计算同步（/quote/price_sync） |

## 1. 环境
- 环境：dev
- Base URL：http://192.168.1.71:13100
- 部署版本：未填写

## 2. 地址
- 方法：POST
- 路径：/quote/price_sync
- 完整 URL：http://192.168.1.71:13100/quote/price_sync

## 3. 请求传参
```json
{
  "requestId": "SAC17954331872020003",
  "orderCode": "TESTSO20261123003",
  "ownerId": "BG",
  "carrierStrategyCode": "VIR|CAR2025062611067266788",
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
      "shipmentCode": "TS20261123003",
      "packages": [
        {
          "packageCode": "QTP20261123003",
          "length": 30,
          "width": 20,
          "height": 15,
          "weight": 2,
          "items": [
            {
              "sku": "SKU-001",
              "qty": 1,
              "length": 30,
              "width": 20,
              "height": 15,
              "weight": 2
            }
          ]
        },
        {
          "packageCode": "QTP20261123003",
          "length": 30,
          "width": 20,
          "height": 15,
          "weight": 2,
          "items": [
            {
              "sku": "SKU-001",
              "qty": 1,
              "length": 30,
              "width": 20,
              "height": 15,
              "weight": 2
            }
          ]
        }
      ]
    }
  ],
  "isPushWms": 200,
  "pushResultTo": 200,
  "closePoboxCheck": 200
}
```
- Headers：Content-Type: application/json
- 复现命令：`未填写`

## 4. 返回结果
- HTTP 状态：HTTP 200
- 耗时：未记录
- 响应体：
```json
{
  "code": "200",
  "msg": "success",
  "success": true,
  "data": [
    {
      "shippingCost": 60.036,
      "bookingCarrierId": "CAR2025062611067266788"
    }
  ]
}
```
- request-id：无
- 日志：无

## 5. 预期结果
- 引用 AC：AC-37
- 需求原文：需求 AC-37：同一请求内 packageCode 重复应被拒绝（失败返回 + 不落任务行）
- 实际 vs 预期：两个包裹同 packageCode 返回成功，金额=2 倍单价（按重复包裹计费）

## 6. 关联用例
| case_id | 用例标题 | AC | 优先级 | 来源 |
|---|---|---|---|---|
| TC-QPS-021 | 契约-结构校验：packageCode 重复（参数化 duplicate-packageCode 条目） | AC-37 | P2 | tests/api/test_quote_price_sync.py |

## 7. 附件
- 无

## 8. 原因分析
- 现象：重复 packageCode 未去重也未拒绝，按 2 个独立包裹计费
- 直接原因：缺少同一请求内 packageCode 唯一性校验
- 根本原因：包裹集合入参未做唯一键校验，重复包裹被当作正常多包裹参与逐包计费求和
- 证据：REQ-002-defects.md D-03（2026-11-23 实测）；2026-11-24 回归 xfail 证实仍在（reports/junit_quote_price_sync.xml）
- 待确认：无

## 9. 影响范围
- 受影响范围：运费重复计算，报价金额虚高；重复包裹行落库造成数据冗余
- 是否偶现：稳定复现
- 关联功能：无

## 10. 修复建议 / 验证建议
- 建议：同一 warehouse.shipment 内 packageCode 唯一性校验，重复按参数校验失败统一拒绝
- 回归范围：TC-QPS-021 全量回归

---

# [BUG-REQ002-D04] pushResultTo=100 非法枚举未被拒绝，仍成功计费

| 字段 | 内容 |
|---|---|
| 缺陷编号 | BUG-REQ002-D04 |
| 状态 | 新建 |
| 严重度 / 优先级 | 中 / P2 |
| 发现版本 | dev 环境当前版本（2026-11-23 实测，2026-11-24 回归仍在） |
| 提交人 / 时间 | wendy / 2026-11-24 |
| 关联需求 | REQ-002 承运商运费计算同步（/quote/price_sync） |

## 1. 环境
- 环境：dev
- Base URL：http://192.168.1.71:13100
- 部署版本：未填写

## 2. 地址
- 方法：POST
- 路径：/quote/price_sync
- 完整 URL：http://192.168.1.71:13100/quote/price_sync

## 3. 请求传参
```json
{
  "requestId": "SAC17954331872020004",
  "orderCode": "TESTSO20261123004",
  "ownerId": "BG",
  "carrierStrategyCode": "VIR|CAR2025062611067266788",
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
      "shipmentCode": "TS20261123004",
      "packages": [
        {
          "packageCode": "QTP20261123004",
          "length": 30,
          "width": 20,
          "height": 15,
          "weight": 1.15,
          "items": [
            {
              "sku": "SKU-001",
              "qty": 1,
              "length": 30,
              "width": 20,
              "height": 15,
              "weight": 1.15
            }
          ]
        }
      ]
    }
  ],
  "isPushWms": 200,
  "pushResultTo": 100,
  "closePoboxCheck": 200
}
```
- Headers：Content-Type: application/json
- 复现命令：`未填写`

## 4. 返回结果
- HTTP 状态：HTTP 200
- 耗时：未记录
- 响应体：
```json
{
  "code": "200",
  "msg": "success",
  "success": true,
  "data": [
    {
      "shippingCost": 19.96,
      "bookingCarrierId": "CAR2025062611067266788"
    }
  ]
}
```
- request-id：无
- 日志：无

## 5. 预期结果
- 引用 AC：AC-08
- 需求原文：需求 §4/AC-08：pushResultTo 合法枚举 0/200/301，非法值应拒绝（统一 500 + 不落任务行）
- 实际 vs 预期：pushResultTo=100 实测返回成功报价，未被拒绝

## 6. 关联用例
| case_id | 用例标题 | AC | 优先级 | 来源 |
|---|---|---|---|---|
| TC-QPS-019 | 契约-枚举校验：非法枚举 isPushWms=300/pushResultTo=100/closePoboxCheck=300（参数化 3 条，全部 xfail） | AC-08 | P2 | tests/api/test_quote_price_sync.py |

## 7. 附件
- 无

## 8. 原因分析
- 现象：pushResultTo=100 请求返回成功报价
- 直接原因：pushResultTo 缺少枚举白名单校验（合法值 0/200/301）
- 根本原因：枚举字段入参未做合法性拦截，非法值被透传到计费流程
- 证据：REQ-002-defects.md D-04（2026-11-23 实测）；2026-11-24 回归 3 条参数化用例 xfail 证实仍在（reports/junit_quote_price_sync.xml）
- 待确认：isPushWms=300 与 closePoboxCheck=300 两条参数化本轮同样未按需求拒绝，需开发一并确认枚举校验范围

## 9. 影响范围
- 受影响范围：非法枚举进入计费流程，若下游按 pushResultTo 分发结果可能产生未定义行为
- 是否偶现：稳定复现
- 关联功能：无

## 10. 修复建议 / 验证建议
- 建议：isPushWms/pushResultTo/closePoboxCheck 增加枚举白名单校验，非法值按统一失败契约拒绝
- 回归范围：TC-QPS-019 全量回归

---

# [BUG-REQ002-D05] 非法策略编码（VIR|、不存在的策略）请求超时不返回，任务停留 status=100

| 字段 | 内容 |
|---|---|
| 缺陷编号 | BUG-REQ002-D05 |
| 状态 | 新建 |
| 严重度 / 优先级 | 中 / P2 |
| 发现版本 | dev 环境当前版本（2026-11-23 实测，2026-11-24 回归仍在） |
| 提交人 / 时间 | wendy / 2026-11-24 |
| 关联需求 | REQ-002 承运商运费计算同步（/quote/price_sync） |

## 1. 环境
- 环境：dev
- Base URL：http://192.168.1.71:13100
- 部署版本：未填写

## 2. 地址
- 方法：POST
- 路径：/quote/price_sync
- 完整 URL：http://192.168.1.71:13100/quote/price_sync

## 3. 请求传参
```json
{
  "requestId": "SAC17954331872027909",
  "orderCode": "TESTSO20261123005",
  "ownerId": "BG",
  "carrierStrategyCode": "NO_SUCH_STRATEGY",
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
      "shipmentCode": "TS20261123005",
      "packages": [
        {
          "packageCode": "QTP20261123005",
          "length": 30,
          "width": 20,
          "height": 15,
          "weight": 1.15,
          "items": [
            {
              "sku": "SKU-001",
              "qty": 1,
              "length": 30,
              "width": 20,
              "height": 15,
              "weight": 1.15
            }
          ]
        }
      ]
    }
  ],
  "isPushWms": 200,
  "pushResultTo": 200,
  "closePoboxCheck": 200
}
```
- Headers：Content-Type: application/json
- 复现命令：`未填写`

## 4. 返回结果
- HTTP 状态：无响应（>30s 客户端 ReadTimeout）
- 耗时：未记录
- 响应体：
```json
{
  "error": "requests.exceptions.ReadTimeout",
  "lsp_quote_task": {
    "request_id": "SAC17954331872027909",
    "status": 100
  }
}
```
- request-id：无
- 日志：无

## 5. 预期结果
- 引用 AC：AC-40
- 需求原文：需求 AC-40/§9.3：策略编码不存在应失败快速返回 code="500" + msg 非空，并落 status=300 任务行
- 实际 vs 预期：实测 >30s 未返回（ReadTimeout），lsp_quote_task 停留 status=100（进行中）

## 6. 关联用例
| case_id | 用例标题 | AC | 优先级 | 来源 |
|---|---|---|---|---|
| TC-QPS-022 | 功能-比价：VIR 段非法（VIR|）（参数化 vir-malformed 条目，xfail） | AC-40 | P2 | tests/api/test_quote_price_sync.py |
| TC-QPS-022 | 功能-比价：策略编码不存在（NO_SUCH_STRATEGY）（参数化 strategy-not-exist 条目，xfail） | AC-40 | P2 | tests/api/test_quote_price_sync.py |

## 7. 附件
- 无

## 8. 原因分析
- 现象：非法策略编码请求挂起超时，任务行停留进行中状态
- 直接原因：策略解析分支对不存在的策略编码未走失败出口，疑似进入重试/轮询等待
- 根本原因：策略编码校验前置缺失：lsp_carrier_strategy 查不到对应记录时未立即返回失败，导致线程阻塞至客户端超时
- 证据：REQ-002-defects.md D-05（2026-11-23 实测，requestId=SAC17954331872027909）；2026-11-24 回归 2 条参数化用例 xfail 证实仍在（reports/junit_quote_price_sync.xml）
- 待确认：「策略绑定空集合」分支 2026-11-24 回归已符合预期（返回 code="500"+msg="No available carrier" 并落 status=300，用例 xpass），疑似部分修复；待开发确认修复范围后收敛本单

## 9. 影响范围
- 受影响范围：调用方线程被挂起 30s+；任务行永久停留 status=100，无失败原因记录
- 是否偶现：稳定复现
- 关联功能：无

## 10. 修复建议 / 验证建议
- 建议：策略编码解析前置校验：VIR 格式非法或 lsp_carrier_strategy 无记录时立即返回统一失败契约并落 status=300
- 回归范围：TC-QPS-022 全量回归 + TC-QPS-024/027（同用 eiz 策略）

---

# [BUG-REQ002-D07] 同时传 carrierIds 与 carrierStrategyCode 时 carrierIds 仍优先生效

| 字段 | 内容 |
|---|---|
| 缺陷编号 | BUG-REQ002-D07 |
| 状态 | 新建 |
| 严重度 / 优先级 | 中 / P2 |
| 发现版本 | dev 环境当前版本（2026-11-23 实测，2026-11-24 回归仍在） |
| 提交人 / 时间 | wendy / 2026-11-24 |
| 关联需求 | REQ-002 承运商运费计算同步（/quote/price_sync） |

## 1. 环境
- 环境：dev
- Base URL：http://192.168.1.71:13100
- 部署版本：未填写

## 2. 地址
- 方法：POST
- 路径：/quote/price_sync
- 完整 URL：http://192.168.1.71:13100/quote/price_sync

## 3. 请求传参
```json
{
  "requestId": "SAC17954331872020007",
  "orderCode": "TESTSO20261123007",
  "ownerId": "BG",
  "carrierStrategyCode": "VIR|CAR2025062611067266788",
  "carrierIds": [
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
      "shipmentCode": "TS20261123007",
      "packages": [
        {
          "packageCode": "QTP20261123007",
          "length": 30,
          "width": 20,
          "height": 15,
          "weight": 1.15,
          "items": [
            {
              "sku": "SKU-001",
              "qty": 1,
              "length": 30,
              "width": 20,
              "height": 15,
              "weight": 1.15
            }
          ]
        }
      ]
    }
  ],
  "isPushWms": 200,
  "pushResultTo": 200,
  "closePoboxCheck": 200
}
```
- Headers：Content-Type: application/json
- 复现命令：`未填写`

## 4. 返回结果
- HTTP 状态：HTTP 200
- 耗时：未记录
- 响应体：
```json
{
  "code": "200",
  "msg": "success",
  "success": true,
  "data": [
    {
      "bookingCarrierId": "CAR1772558358570467346"
    }
  ]
}
```
- request-id：无
- 日志：无

## 5. 预期结果
- 引用 AC：AC-43
- 需求原文：需求 Q-014/C-15：接口层只认 carrierStrategyCode，carrierIds 仅兼容保留、不参与选承运商
- 实际 vs 预期：双向实测均以 carrierIds 为准：VIR|PRO + carrierIds=[Aramex] → 返回 Aramex；VIR|Aramex + carrierIds=[PRO] → 返回 PRO

## 6. 关联用例
| case_id | 用例标题 | AC | 优先级 | 来源 |
|---|---|---|---|---|
| TC-QPS-031 | 功能-比价：同时传 carrierIds 与 VIR|PRO → 只按策略返回 PRO（xfail） | AC-43 | P2 | tests/api/test_quote_price_sync.py |

## 7. 附件
- 无

## 8. 原因分析
- 现象：carrierIds 存在时覆盖 carrierStrategyCode 的选商结果
- 直接原因：承运商选择逻辑仍优先读取 carrierIds 兼容字段
- 根本原因：V1.6 口径（接口层只认 carrierStrategyCode）未在选商代码路径落地，旧 carrierIds 优先级未降级
- 证据：REQ-002-defects.md D-07（2026-11-23 双向实测）；2026-11-24 回归 xfail 证实仍在（reports/junit_quote_price_sync.xml）
- 待确认：无

## 9. 影响范围
- 受影响范围：上层按策略下发请求时实际承运商与策略意图不一致，比价/最优结果失真
- 是否偶现：稳定复现
- 关联功能：无

## 10. 修复建议 / 验证建议
- 建议：选商入口移除 carrierIds 优先级：仅当 carrierStrategyCode 为空时才按兼容逻辑兜底（或直接忽略 carrierIds）
- 回归范围：TC-QPS-031 + TC-QPS-036[carrierIds] 回归

---

# [BUG-REQ002-D08] 未知仓库 WH-NOT-EXIST-0000 未按计费失败处理，仍返回成功报价

| 字段 | 内容 |
|---|---|
| 缺陷编号 | BUG-REQ002-D08 |
| 状态 | 新建 |
| 严重度 / 优先级 | 中 / P2 |
| 发现版本 | dev 环境当前版本（2026-11-23 实测，2026-11-24 回归仍在） |
| 提交人 / 时间 | wendy / 2026-11-24 |
| 关联需求 | REQ-002 承运商运费计算同步（/quote/price_sync） |

## 1. 环境
- 环境：dev
- Base URL：http://192.168.1.71:13100
- 部署版本：未填写

## 2. 地址
- 方法：POST
- 路径：/quote/price_sync
- 完整 URL：http://192.168.1.71:13100/quote/price_sync

## 3. 请求传参
```json
{
  "requestId": "SAC17954331295155049",
  "orderCode": "TESTSO20261123008",
  "ownerId": "BG",
  "carrierStrategyCode": "VIR|CAR1772558358570467346",
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
      "warehouseCode": "WH-NOT-EXIST-0000",
      "shipmentCode": "TS20261123008",
      "packages": [
        {
          "packageCode": "QTP20261123008",
          "length": 30,
          "width": 20,
          "height": 15,
          "weight": 2,
          "items": [
            {
              "sku": "SKU-001",
              "qty": 1,
              "length": 30,
              "width": 20,
              "height": 15,
              "weight": 2
            }
          ]
        }
      ]
    }
  ],
  "isPushWms": 200,
  "pushResultTo": 200,
  "closePoboxCheck": 200
}
```
- Headers：Content-Type: application/json
- 复现命令：`未填写`

## 4. 返回结果
- HTTP 状态：HTTP 200
- 耗时：未记录
- 响应体：
```json
{
  "code": "200",
  "msg": "success",
  "success": true,
  "data": [
    {
      "shippingCost": 5.724,
      "bookingCarrierId": "CAR1772558358570467346"
    }
  ],
  "lsp_quote_task": {
    "request_id": "SAC17954331295155049",
    "status": 200
  }
}
```
- request-id：无
- 日志：无

## 5. 预期结果
- 引用 AC：AC-32
- 需求原文：需求 C-04：未知仓库按计费失败处理（返回统一失败契约 + 落 status=300 任务行 + job_log 原因）
- 实际 vs 预期：实测 code="200"、返回 1 行报价（Aramex 5.724），落库 status=200

## 6. 关联用例
| case_id | 用例标题 | AC | 优先级 | 来源 |
|---|---|---|---|---|
| TC-QPS-014 | 异常与落库：未知仓库 → 500 且落 status=300（参数化 unknown-warehouse 条目，xfail） | AC-32 | P2 | tests/api/test_quote_price_sync.py |

## 7. 附件
- 无

## 8. 原因分析
- 现象：lsp_warehouse 不存在的仓库编码仍完成计费并返回成功
- 直接原因：仓库主数据查询失败后未走计费失败分支，走了默认/兜底计价逻辑
- 根本原因：发运仓主数据校验缺失：未按仓库 from_facility 解析 zone 的失败场景兜底为计费失败，而是跳过仓库维度直接出价
- 证据：REQ-002-defects.md D-08（2026-11-23 实测，requestId=SAC17954331295155049 落库 status=200）；2026-11-24 回归 xfail 证实仍在（reports/junit_quote_price_sync.xml）
- 待确认：无

## 9. 影响范围
- 受影响范围：仓库主数据错误的请求可拿到看似合法的报价，落库任务状态失真（status=200），计费口径不可信
- 是否偶现：稳定复现
- 关联功能：无

## 10. 修复建议 / 验证建议
- 建议：warehouseCode 实查 lsp_warehouse 失败时按计费失败处理：返回统一失败契约并落 status=300 + job_log 记录原因
- 回归范围：TC-QPS-014 全量回归

---

# [BUG-REQ002-D09] VIR 携带不存在的 carrierId 被静默忽略，仍返回有效承运商报价

| 字段 | 内容 |
|---|---|
| 缺陷编号 | BUG-REQ002-D09 |
| 状态 | 新建 |
| 严重度 / 优先级 | 中 / P2 |
| 发现版本 | dev 环境当前版本（2026-11-23 实测，2026-11-24 回归仍在） |
| 提交人 / 时间 | wendy / 2026-11-24 |
| 关联需求 | REQ-002 承运商运费计算同步（/quote/price_sync） |

## 1. 环境
- 环境：dev
- Base URL：http://192.168.1.71:13100
- 部署版本：未填写

## 2. 地址
- 方法：POST
- 路径：/quote/price_sync
- 完整 URL：http://192.168.1.71:13100/quote/price_sync

## 3. 请求传参
```json
{
  "requestId": "SAC17954331326055123",
  "orderCode": "TESTSO20261123009",
  "ownerId": "BG",
  "carrierStrategyCode": "VIR|CAR1772558358570467346|CAR-NOT-EXIST-000000",
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
      "shipmentCode": "TS20261123009",
      "packages": [
        {
          "packageCode": "QTP20261123009",
          "length": 30,
          "width": 20,
          "height": 15,
          "weight": 1.15,
          "items": [
            {
              "sku": "SKU-001",
              "qty": 1,
              "length": 30,
              "width": 20,
              "height": 15,
              "weight": 1.15
            }
          ]
        }
      ]
    }
  ],
  "isPushWms": 200,
  "pushResultTo": 200,
  "closePoboxCheck": 200
}
```
- Headers：Content-Type: application/json
- 复现命令：`未填写`

## 4. 返回结果
- HTTP 状态：HTTP 200
- 耗时：未记录
- 响应体：
```json
{
  "code": "200",
  "msg": "success",
  "success": true,
  "data": [
    {
      "shippingCost": 5.724,
      "bookingCarrierId": "CAR1772558358570467346"
    }
  ],
  "lsp_quote_task": {
    "request_id": "SAC17954331326055123",
    "status": 200
  }
}
```
- request-id：无
- 日志：无

## 5. 预期结果
- 引用 AC：AC-39
- 需求原文：需求 Q-014：VIR 段 carrierId 不存在应返回统一失败契约（code="500"）且不落任务行
- 实际 vs 预期：实测 code="200"，不存在的 carrierId 被静默剔除后仍返回 Aramex 5.724，落库 status=200

## 6. 关联用例
| case_id | 用例标题 | AC | 优先级 | 来源 |
|---|---|---|---|---|
| TC-QPS-014 | 异常与落库：VIR 中不存在 carrierId → 500 且不落行（参数化 unknown-carrier 条目，xfail） | AC-39 | P2 | tests/api/test_quote_price_sync.py |

## 7. 附件
- 无

## 8. 原因分析
- 现象：VIR 策略编码中的非法 carrierId 被剔除，剩余有效承运商照常计费
- 直接原因：承运商 ID 解析时对查不到主数据的 ID 做静默过滤而非报错
- 根本原因：VIR 段解析缺少 ID 存在性校验：需求要求整体失败，实现按"能算几个算几个"容错处理
- 证据：REQ-002-defects.md D-09（2026-11-23 实测，requestId=SAC17954331326055123 落库 status=200）；2026-11-24 回归 xfail 证实仍在（reports/junit_quote_price_sync.xml）
- 待确认：无

## 9. 影响范围
- 受影响范围：上层传错的 carrierId 不会被察觉，比价范围悄然缩小，最优结果可能失真
- 是否偶现：稳定复现
- 关联功能：无

## 10. 修复建议 / 验证建议
- 建议：VIR 段逐个校验 carrierId 存在性，任一不存在按统一失败契约拒绝且不落任务行
- 回归范围：TC-QPS-014 全量回归

---

# [BUG-REQ002-D10] orderCode=32 字符（需求上界）落库追加 6 位序号后超 varchar(32) 列宽

| 字段 | 内容 |
|---|---|
| 缺陷编号 | BUG-REQ002-D10 |
| 状态 | 新建 |
| 严重度 / 优先级 | 中 / P2 |
| 发现版本 | dev 环境当前版本（2026-11-24 本轮实测） |
| 提交人 / 时间 | wendy / 2026-11-24 |
| 关联需求 | REQ-002 承运商运费计算同步（/quote/price_sync） |

## 1. 环境
- 环境：dev
- Base URL：http://192.168.1.71:13100
- 部署版本：未填写

## 2. 地址
- 方法：POST
- 路径：/quote/price_sync
- 完整 URL：http://192.168.1.71:13100/quote/price_sync

## 3. 请求传参
```json
{
  "requestId": "SAC17954980000000001",
  "orderCode": "TESTSO20261124140000000XXXXXXXXXX",
  "ownerId": "BG",
  "carrierStrategyCode": "VIR|CAR2025062611067266788",
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
      "shipmentCode": "TS20261124001",
      "packages": [
        {
          "packageCode": "QTP20261124001",
          "length": 30,
          "width": 20,
          "height": 15,
          "weight": 1.15,
          "items": [
            {
              "sku": "SKU-001",
              "qty": 1,
              "length": 30,
              "width": 20,
              "height": 15,
              "weight": 1.15
            }
          ]
        }
      ]
    }
  ],
  "isPushWms": 200,
  "pushResultTo": 200,
  "closePoboxCheck": 200
}
```
- Headers：Content-Type: application/json
- 复现命令：`未填写`

## 4. 返回结果
- HTTP 状态：HTTP 200
- 耗时：未记录
- 响应体：
```json
{
  "code": "200",
  "msg": "success",
  "success": true,
  "note": "接口层成功；落库 lsp_quote_task.order_code 追加「-6位序号」后达 39 字符，超出 varchar(32) 列宽（截断或写失败）"
}
```
- request-id：无
- 日志：无

## 5. 预期结果
- 引用 AC：AC-07
- 需求原文：需求 AC-07：orderCode=32 字符恰好上界应成功计费、不因长度误拒；落库实现需与需求上限自洽
- 实际 vs 预期：需求允许 32 字符，但落库实现叠加「-6 位序号」后超出 lsp_quote_task.order_code varchar(32)，需求上限与落库实现冲突

## 6. 关联用例
| case_id | 用例标题 | AC | 优先级 | 来源 |
|---|---|---|---|---|
| TC-QPS-035 | 契约-长度校验：orderCode=32 恰好上界（参数化 orderCode 条目，xfail） | AC-07 | P2 | tests/api/test_quote_price_sync.py |

## 7. 附件
- 无

## 8. 原因分析
- 现象：orderCode 恰好 32 字符（合法上界）请求在落库环节失败
- 直接原因：落库时 order_code 列值 = 入参 orderCode + 「-6 位序号」，39 字符 > 列宽 varchar(32)
- 根本原因：需求（orderCode ≤32）与落库设计（追加 6 位序号且列宽 32）相互冲突，两侧均未为对方留出余量
- 证据：2026-11-24 回归 test_length_at_upper_bound[orderCode] xfail（reports/junit_quote_price_sync.xml）；本轮新增记录，REQ-002-defects.md 此前未收录
- 待确认：需求方确认口径：扩列宽 / 落库不追加序号 / 收紧需求上界到 26 字符，三选一后对齐实现与用例

## 9. 影响范围
- 受影响范围：恰好上界的合法 orderCode 无法完整落库；相邻长度（26~32 字符）均可能受影响
- 是否偶现：稳定复现
- 关联功能：无

## 10. 修复建议 / 验证建议
- 建议：按需求确认结果三选一：lsp_quote_task.order_code 扩到 varchar(40)；或落库改为复用入参 orderCode 不追加序号；或需求收紧 orderCode 上界，同步更新 AC-07 与用例
- 回归范围：TC-QPS-035/TC-QPS-036 长度相关用例全量回归


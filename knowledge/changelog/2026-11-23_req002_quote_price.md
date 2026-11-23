---
change_ids: [CHG-003]
module: lsp_quote
feature: quote_price
date: 2026-11-23
type: new_feature
---

# 2026-11-23：REQ-002 承运商运费同步接口进入自动化回归

## 变更概要
`POST /quote/price_sync`（REQ-002 V1.1）完成自动化用例落库，建立
`testcases/REQ-002-TC-list.yaml` 用例清单与 `tests/api/test_quote_price_sync.py`
脚本的双向映射，回归索引从设计稿编号切换为可执行编号。

## 具体变更
- 新增用例清单：`testcases/REQ-002-TC-list.yaml`（15 条，覆盖 22 个 AC）
- 脚本：`tests/api/test_quote_price_sync.py`（15 个测试函数 / 21 个可执行实例）
- 回归目标：TC-QPS-001 ~ TC-QPS-015
- 金额断言口径：lsp_scp 验证 SQL 现算现比（half-up 三位），不复制需求示例值

## 影响用例
```
TC-QPS-001  主流程双承运商
TC-QPS-002  幂等重放
TC-QPS-003  新 requestId 同 orderCode
TC-QPS-004  zone 映射切换
TC-QPS-005  多包裹求和
TC-QPS-006  续重段 >5kg
TC-QPS-007  承运商内部择优
TC-QPS-008  包裹层 0 取 SKU / 组包
TC-QPS-009  超箱规过滤
TC-QPS-010  箱规边界
TC-QPS-011  PO Box 过滤
TC-QPS-012  无价卡承运商跳过
TC-QPS-013  参数校验族
TC-QPS-014  主数据不存在族
TC-QPS-015  鉴权拒绝
```

## 遗留缺口
- 地址校验、carrier_a 计费配置暂无自动化脚本，已在 impact-index 中登记
  `coverage_gap`，不占用回归目标。
- 需回填校准点：`carrier_no_rate_id`、`au_post_carrier_id`、`destinations.dest_b`
  （见 `config/lsp_quote/price_sync.yaml` 注释）。

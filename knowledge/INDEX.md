# 知识库入口索引

> 本目录是 AI 在设计用例、评审变更、判断回归范围时的"必读手册"。
> 所有 Skill（design-testcases / split-requirements / test-workflow）
> 在执行前应先读取本文件，找到对应的规则和影响索引。

## 快速导航

| 我想知道 | 去哪看 |
|----------|--------|
| 地址校验业务规则 v2.1 | [rules/lsp_backend/address_validation.md](rules/lsp_backend/address_validation.md) |
| 计费/报价规则 | [rules/lsp_quote/](rules/lsp_quote/) |
| 承运商 A v1.2 → v2.0 改了什么 | [changelog/2026-11-20_quote_carrier_a_v2.md](changelog/2026-11-20_quote_carrier_a_v2.md) |
| PO Box 正则大小写不敏感踩坑 | [gotchas/gotcha_001_pobox_case.md](gotchas/gotcha_001_pobox_case.md) |
| DB 字段 NOT NULL 但 API 返回空串 | [gotchas/gotcha_002_db_null.md](gotchas/gotcha_002_db_null.md) |
| 改了某个规则该回归哪些用例 | [impact-index.yaml](impact-index.yaml) |
| Apifox 接口文档地址 | [references/apifox.md](references/apifox.md) |
| 术语表 | [references/glossary.md](references/glossary.md) |
| 关键表结构 | [references/db_schema.md](references/db_schema.md) |

## 模块 → 承运商 → 版本 映射

```
LspBackend（基础信息配置）
  └── address_validation    v2.1 confirmed（唯一版本，无承运商差异）
  └── strategy_config       —— 承运商无关的通用策略配置

LspQuote（物流计费）
  ├── pricing（通用规则）
  ├── carrier_a
  │   ├── v1.2（当前线上）
  │   └── v2.0（开发中，2026-12-01 上线）
  └── carrier_b
      └── v1.0

LspBooking（物流申报）
  ├── carrier_a
  │   └── v1.0
  └── carrier_b
      └── v1.0
```

## 维护约定

1. **每次规则变更**：在 `changelog/` 新增日期文件，同时更新 `impact-index.yaml`。
2. **每次踩坑**：在 `gotchas/` 新增编号文件，在被踩坑的用例/配置旁边加注释链接。
3. **impact-index.yaml 必须可机读**：Skill 和脚本直接解析它来判断回归范围。
4. **规则文档第一行必须写版本号**：`v2.1 confirmed by 业务方 2026-11-15`。
5. **待确认事项统一标【待确认】**：写在规则里，别藏在测试用例的 `skip` reason 里。

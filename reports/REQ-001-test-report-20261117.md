# REQ-001 地址校验接口 测试报告

## 1. 报告信息

| 项目 | 内容 |
|---|---|
| 需求 | REQ-001 地址校验接口 `POST /address/validate` |
| 环境 | 测试环境 |
| Base URL | `http://192.168.1.71:13109` |
| 数据库 | `192.168.1.31:13306` / `lsp_dev` |
| 分支 / 提交 | `feature/ai-test-automation` / `f5ce1ec` |
| 执行范围 | `tests/api/test_address_validate.py`（38 条） |
| 执行时间 | 2026-11-17 |
| 执行方式 | `python -m pytest tests/api/test_address_validate.py --junitxml=reports/junit.xml --html=reports/report.html` |
| 数据源 | `reports/junit.xml`、`REQ-001-TC-design-v2.xlsx` |

## 2. 结论摘要

| 指标 | 数值 |
|---|---|
| 总计 | 38 |
| 通过 | 24 |
| 失败 | 1 |
| 跳过 | 11 |
| XPASS（xfail 但实际通过） | 2 |
| 耗时 | 1.55s |
| 有效执行率 | 71.1%（27/38，skip 不计入分母） |
| 非跳过通过率 | 96.3%（26/27，XPASS 计入通过） |

结论：**不通过**。存在 1 条 P1 用例失败，且 2 条 P0 用例全部跳过、13 条设计用例尚未落地脚本，核心路径未被完整验证。

## 3. 模块统计

| 模块 | 选中 | 通过 | 失败 | 跳过 | 耗时 |
|---|---|---|---|---|---|
| 地址校验接口 | 38 | 26（含 2 XPASS） | 1 | 11 | 1.42s |

最慢用例：TC-ADDR-051（0.27s）、TC-ADDR-022（0.18s）、TC-ADDR-050（0.18s）。

## 4. 用例明细

| 用例编号 | 用例标题 | 关联 AC | 优先级 | 结果 | 耗时(s) | 测试函数 |
|---|---|---|---|---|---|---|
| TC-ADDR-003 | 非澳大利亚国家提交时返回校验失败 | AC-03 | P1 | 通过 | 0.03 | test_non_australia_country_rejected |
| TC-ADDR-004 | 主键命中但街道文本不存在时仍校验通过 | AC-01 | P1 | 通过 | 0.03 | test_arbitrary_street_text_still_valid |
| TC-ADDR-008 | 主键大小写与前后空格变体处理 | AC-02 | P1 | 跳过 | 0.00 | test_key_case_and_whitespace |
| TC-ADDR-009 | 主键字段为 null 或空字符串时返回参数校验错误 | AC-02 | P1 | 失败 | 0.04 | test_null_or_empty_key_fields |
| TC-ADDR-010 | 邮编前导零必须按字符串匹配（0800 vs 800） | AC-02 | P2 | 通过 | 0.03 | test_postcode_leading_zero |
| TC-ADDR-011 | 澳大利亚名称与 ISO 编码写法兼容性 | AC-03 | P1 | 通过 | 0.06 | test_country_variants |
| TC-ADDR-012 | country 为空字符串或 null 时的默认值处理 | AC-03 | P2 | 跳过 | 0.00 | test_country_empty_or_null |
| TC-ADDR-014 | 未传 order_id 时响应正常且不回填 | AC-04 | P1 | 通过 | 0.04 | test_order_id_missing |
| TC-ADDR-015 | order_id 超长与特殊字符原样回传 | AC-04 | P2 | 通过 | 0.04 | test_order_id_edge_values |
| TC-ADDR-016 | is_return=true 时返回建议地址 | AC-05 | P1 | 跳过 | 0.00 | test_is_return_true |
| TC-ADDR-017 | is_return=false 时建议地址返回策略 | AC-05 | P1 | 跳过 | 0.00 | test_is_return_false |
| TC-ADDR-018 | is_return 传非布尔值时参数校验 | AC-05 | P2 | 跳过 | 0.00 | test_is_return_non_boolean |
| TC-ADDR-022 | PO Box 正则正向变体全部识别 | AC-06 | P1 | 通过 | 0.18 | test_pobox_positive_variants |
| TC-ADDR-023 | PO Box 正则负向变体不得误判 | AC-06 | P1 | 通过 | 0.06 | test_pobox_negative_variants |
| TC-ADDR-024 | PO Box 大小写与空白/标点变体识别 | AC-06 | P1 | 通过 | 0.06 | test_pobox_case_variants |
| TC-ADDR-025 | 主键不存在且地址为 PO Box 时先返回 address not found | AC-06 | P1 | 通过 | 0.02 | test_not_found_short_circuits_pobox |
| TC-ADDR-026 | address 为 null 且 address2 命中时仍识别 PO Box | AC-06 | P2 | 通过 | 0.01 | test_pobox_with_null_address |
| TC-ADDR-028 | postcode 格式非法时不得命中 | AC-07 | P1 | 通过 | 0.04 | test_invalid_postcode_format |
| TC-ADDR-029 | suburb 特殊字符或超长时不得命中 | AC-07 | P1 | 通过 | 0.03 | test_suburb_special_or_long |
| TC-ADDR-030 | state 全称自动转简称后匹配数据库 | AC-07 | P1 | 通过 | 0.03 | test_state_full_name |
| TC-ADDR-031 | postcode 传数字类型时的处理 | AC-07 | P2 | 跳过 | 0.00 | test_postcode_numeric_type |
| TC-ADDR-033 | address 缺失但主键齐全时校验通过 | AC-08 | P1 | 通过 | 0.01 | test_address_optional |
| TC-ADDR-034 | 未知字段处理策略 | AC-08 | P2 | 通过 | 0.02 | test_unknown_field_ignored |
| TC-ADDR-035 | 非法 JSON 与错误 Content-Type 的处理 | AC-08 | P2 | 跳过 | 0.00 | test_invalid_json_and_content_type |
| TC-ADDR-036 | address 超长但主键命中时仍校验通过 | AC-09 | P1 | 通过 | 0.03 | test_long_address_still_valid |
| TC-ADDR-037 | address 注入载荷不影响存在性且无注入风险 | AC-09 | P1 | 通过 | 0.03 | test_injection_payload_still_valid |
| TC-ADDR-038 | 中文与 emoji address 不影响存在性校验 | AC-09 | P2 | 通过 | 0.03 | test_unicode_address_still_valid |
| TC-ADDR-040 | 相同请求重复提交结果一致 | AC-11 | P1 | 通过 | 0.05 | test_repeated_calls_consistent |
| TC-ADDR-041 | 并发提交同一请求结果一致 | AC-11 | P2 | 通过 | 0.03 | test_concurrent_calls_consistent |
| TC-ADDR-042 | 地址表数据库不可用时返回明确失败 | AC-12 | P0 | 跳过 | 0.00 | test_db_unavailable |
| TC-ADDR-043 | 地址表查询超时时在阈值内返回错误 | AC-12 | P1 | 跳过 | 0.00 | test_db_timeout |
| TC-ADDR-044 | 成功响应包装结构与字段类型完整性 | AC-13 | P0 | 跳过 | 0.00 | test_success_envelope_schema |
| TC-ADDR-046 | 响应 Content-Type 与 JSON 可解析性 | AC-13 | P1 | 通过 | 0.03 | test_content_type_json |
| TC-ADDR-047 | address2 回显并参与 fullAddress 拼接 | AC-14 | P1 | 跳过 | 0.00 | test_address2_full_address |
| TC-ADDR-048 | address2 超长与特殊字符不影响存在性 | AC-14 | P2 | 通过 | 0.03 | test_address2_long_special |
| TC-ADDR-049 | 州与区域返回对应编码 | AC-15 | P1 | 通过 | 0.03 | test_state_suburb_codes |
| TC-ADDR-050 | 8 个州简称与全称参数化校验 | AC-15 | P1 | 通过 | 0.18 | test_all_states_abbrev_and_full |
| TC-ADDR-051 | 乱码与非澳洲文本在存在性校验中不影响结果 | AC-16 | P1 | 通过 | 0.27 | test_random_and_non_au_text_still_valid |

## 5. 失败明细

### TC-ADDR-009 主键字段为 null 或空字符串时返回参数校验错误

| 项目 | 内容 |
|---|---|
| 关联 AC | AC-02（主键缺失/为空时返回明确错误） |
| 优先级 | P1 |
| 现象 | `state=""` 时接口未在参数校验阶段拦截，返回业务失败 `reason="address not found"` |
| 请求 | `POST /address/validate`，`base` 数据覆盖 `{"state": ""}`，其余字段为合法值（suburb=Sydney、postcode=2000、country=Australia） |
| 实际返回 | HTTP 200，外层 `success=true`、`code=200`；`data.success=false`，`data.reason="address not found"` |
| 预期结果 | state 为空时 `reason="state not found"` |
| 对比结论 | `postcode=""`、`suburb=""` 同样落入 `address not found`，未按字段给出具体缺失原因 |
| 归因 | E 真实缺陷（错误提示不精确，空字符串未按字段校验）；若产品确认允许空字符串，则改为 D 预期不一致 |
| 严重程度 | S3（错误提示不准确，不影响主流程成功路径） |
| 证据 | `reports/report.html`、`reports/junit.xml`、测试函数 `test_null_or_empty_key_fields` |

补充证据：`state=None` 时行为不同——HTTP 200、外层 `success=false`、`code=400`、`msg="Validate failed, [state]: 缺少省份"`，说明 null 与空字符串走了两套逻辑。

## 6. 跳过明细

| 用例编号 | 跳过原因 | 影响 |
|---|---|---|
| TC-ADDR-008 | 待确认：DB 对 state/suburb 大小写与前后空格是否敏感 | 大小写兼容性未验证 |
| TC-ADDR-012 | 待确认：country 为空/null 是否等同默认 Australia | 默认值策略未验证 |
| TC-ADDR-016 | 待确认：is_return=true 时 adviceAddress 生成规则 | 建议地址能力未验证 |
| TC-ADDR-017 | 待确认：is_return=false 时是否仍返回 adviceAddress | 建议地址能力未验证 |
| TC-ADDR-018 | 待确认：is_return 非布尔值反序列化策略 | 参数健壮性未验证 |
| TC-ADDR-031 | 待确认：postcode 数字类型反序列化策略 | 参数健壮性未验证 |
| TC-ADDR-035 | 待确认：非法 JSON / 错误 Content-Type 契约 | 错误响应契约未验证 |
| TC-ADDR-042 | 需要故障注入使地址表不可用 | **P0 未验证** |
| TC-ADDR-043 | 需要故障注入使地址表查询超时 | 降级能力未验证 |
| TC-ADDR-044 | 待确认：OpenAPI 未声明 required，data 是否固定 15 字段 | **P0 未验证** |
| TC-ADDR-047 | 待确认：fullAddress 拼接顺序与 address2 规则 | 拼接规则未验证 |

## 7. 覆盖分析

### AC 覆盖

| 指标 | 数值 |
|---|---|
| 设计 AC 总数 | 16 |
| 有用例执行的 AC | 15 / 16（93.8%） |
| 有通过用例的 AC | 13 / 16（81.3%） |
| 未执行的 AC | AC-10（无对应脚本） |
| 全部跳过、无通过用例的 AC | AC-05、AC-12 |

### 分 AC 明细

| AC | 设计用例 | 已执行 | 通过 | 失败 | 跳过 | 无脚本 |
|---|---|---|---|---|---|---|
| AC-01 | 2 | 1 | 1 | 0 | 0 | 1 |
| AC-02 | 7 | 3 | 1 | 1 | 1 | 4 |
| AC-03 | 3 | 3 | 2 | 0 | 1 | 0 |
| AC-04 | 3 | 2 | 2 | 0 | 0 | 1 |
| AC-05 | 3 | 3 | 0 | 0 | 3 | 0 |
| AC-06 | 8 | 5 | 5 | 0 | 0 | 3 |
| AC-07 | 5 | 4 | 3 | 0 | 1 | 1 |
| AC-08 | 4 | 3 | 2 | 0 | 1 | 1 |
| AC-09 | 3 | 3 | 3 | 0 | 0 | 0 |
| AC-10 | 1 | 0 | 0 | 0 | 0 | 1 |
| AC-11 | 2 | 2 | 2 | 0 | 0 | 0 |
| AC-12 | 2 | 2 | 0 | 0 | 2 | 0 |
| AC-13 | 3 | 2 | 1 | 0 | 1 | 1 |
| AC-14 | 2 | 2 | 1 | 0 | 1 | 0 |
| AC-15 | 2 | 2 | 2 | 0 | 0 | 0 |
| AC-16 | 1 | 1 | 1 | 0 | 0 | 0 |

### 用例落地情况

- 设计用例 51 条，脚本落地 38 条，落地率 74.5%。
- 未落地：TC-ADDR-001、002、005、006、007、013、019、020、021、027、032、039、045，共 13 条。
- 未落地用例集中在 AC-02（4 条）与 AC-06（3 条），主键校验和 PO Box 仍存在覆盖缺口。

### 数据库断言

- 21 个成功路径用例已接入 `lsp_address_suburb_postcode` 命中校验（state/postcode/suburb，suburb 大小写不敏感）。
- 本轮全部执行通过，数据库连通与数据一致性未发现问题。

## 8. 风险与待确认

| 编号 | 风险 / 待确认项 | 影响 |
|---|---|---|
| Q-01 | `state=""` 期望 `state not found`，实际 `address not found` | 接口错误提示契约未定 |
| Q-02 | 2 条 P0 用例（TC-ADDR-042/044）全部跳过 | 核心容错与响应结构未验证 |
| Q-03 | 13 条设计用例未落地脚本 | AC-02/AC-06 覆盖不足 |
| Q-04 | 7 条契约类用例因需求未确认而跳过 | is_return、country 默认值、类型容错未知 |
| Q-05 | 故障注入环境缺失 | 数据库降级路径无法验证 |
| Q-06 | DB 大小写敏感策略未确认（TC-ADDR-008） | 可能影响真实用户匹配结果 |

## 9. 结论与下一步

**结论：不通过**。主流程 96.3% 的已执行用例通过，但存在 1 条 P1 失败、2 条 P0 未执行、13 条设计用例缺失，尚不足以支撑发布。

下一步：

1. 确认 Q-01：空字符串主键应返回字段级 `not found` 还是统一 `address not found`；确认后修复断言或按 `bug-analysis` 提缺陷（S3）。
2. 补齐 AC-02、AC-06 的 7 条缺失脚本，优先 TC-ADDR-002/005/006/007。
3. 为 TC-ADDR-044 去掉跳过条件（OpenAPI required 问题需产品确认），补 P0 响应结构校验。
4. 搭建地址库故障注入能力，执行 TC-ADDR-042/043。
5. 移除 TC-ADDR-024、049 的 `xfail` 标记，避免长期 XPASS 掩盖回归。

# REQ-001 地址校验 失败用例分析

- 需求：REQ-001
- 环境：`http://192.168.1.71:13109`
- 分支 / commit：`master` / `f5ce1ec`（工作区含未提交修改）
- 执行时间：2026-11-17 15:33–15:43
- 数据来源：`reports/REQ-001-test-report-20261117-1543.md`、`reports/junit.xml`、pytest 控制台输出

## 1. 失败总览

| case_id | 用例 | 结果 | 归因 | 是否产品缺陷 | 处理 |
|---|---|---|---|---|---|
| TC-ADDR-009 | `test_null_or_empty_key_fields` | FAIL | D 预期不一致 | 待确认 | 产品确认后决定是否转 E |
| TC-ADDR-003 | `test_non_australia_country_rejected` | FAIL | C 脚本缺陷 | 否 | 转 test-script |
| TC-ADDR-028 | `test_invalid_postcode_format` | FAIL | C 脚本缺陷 | 否 | 转 test-script |

> 本次没有可直接提交的 E 类产品缺陷。`BUG-REQ001-001` 状态为“待确认”。

## 2. TC-ADDR-009 —— D 类预期不一致（待确认）

### 2.1 现象

主键字段 `state`/`postcode`/`suburb` 之一为 `null` 或空字符串时：

- 期望：参数校验错误，`code=400`、`data=null`、`wrapper.success=false`、`msg` 指出缺失字段。
- 实际：`HTTP 200`、`wrapper.success=true`、`code="200"`、`data.success=false`、`data.reason="address not found"`、`data` 为对象。

### 2.2 证据

实际响应（`state=null`）：

```json
{
  "data": {
    "success": false,
    "reason": "address not found",
    "state": "",
    "suburb": "Sydney",
    "postcode": "2000",
    "country": "Australia",
    "isPoBox": false
  },
  "code": "200",
  "msg": "",
  "success": true
}
```

对照：TC-ADDR-027（字段**缺失**）实际返回 `code="400"`、`data=null`、`msg="Validate failed, [state]: 缺少省份"`。

### 2.3 根因

- 现象：null/空串被当作“查无匹配”。
- 直接原因：实现只在字段缺失时触发参数校验；字段存在但为 null/空串时继续查库，查无结果后返回 `address not found`。
- 根本原因：设计文档 v2.2 把“缺失 / null / 空串”统一写成参数校验错误，但实现区分了“缺失”和“存在但为空”。
- 证据：实际响应 `data.reason="address not found"`；TC-ADDR-027 的 `code=400 + data=null`。

### 2.4 影响面

- 受影响入参：`state`、`postcode`、`suburb` 为 null 或空字符串。
- 是否放行非法地址：否，`data.success=false`，请求仍被拒绝。
- 影响点：错误分类、错误码、前端提示、调用方重试策略。
- 是否偶现：稳定复现（本次全量执行 1/1）。

### 2.5 定级建议

- 若产品确认“应返回参数校验错误”：**S3 / P2**（边界语义，非核心流程中断）。
- 若产品确认“address not found 可接受”：转为测试/文档修正，不提缺陷。

### 2.6 待确认

`state/postcode/suburb` 为 null/空串时，产品要求：

1. 参数校验错误（`code=400`、`data=null`、`msg` 指出缺失字段）；或
2. 查无匹配（`address not found`）。

## 3. TC-ADDR-003 —— C 类脚本缺陷

### 3.1 现象

```
KeyError: 'msg'
tests/api/test_address_validate.py:115
```

### 3.2 根因

- `utils/api_assertions.py::assert_rejected` 在“HTTP 200 + 业务失败（data 为对象）”分支返回 `data` 字典。
- 调用方 `test_non_australia_country_rejected` 按 envelope 读取 `body["msg"]`，触发 `KeyError`。
- `assert_rejected` 的文档写“Returns the parsed envelope”，实现与文档不一致。

### 3.3 影响面

- 仅影响使用 `assert_rejected` 且读取 envelope 字段的脚本。
- 接口行为本身未被否定。

### 3.4 修复建议

`assert_rejected` 在业务失败分支执行 `assert_business_failure(...)` 后返回 `body`（envelope），统一返回契约。转 `test-script`。

## 4. TC-ADDR-028 —— C 类脚本缺陷

### 4.1 现象

```
KeyError: 'msg'
tests/api/test_address_validate.py:306
```

### 4.2 根因

与 TC-ADDR-003 完全相同：`assert_rejected` 返回 `data` 而非 envelope。

### 4.3 修复建议

同 TC-ADDR-003；修复后补 reason/msg 断言（`address not found` / `postcode` / `邮编`）。

## 5. 结论与下一步

- **产品缺陷：0 条**。TC-ADDR-009 为 D 类待确认；TC-ADDR-003/028 为 C 类脚本缺陷。
- **已生成待确认缺陷记录**：`reports/bugs/BUG-REQ001-001.yaml`（生成 `.md` / `.xlsx` 需执行 bug-analysis 脚本）。
- **下一步**：
  1. 产品确认 TC-ADDR-009 的预期错误语义。
  2. 转 `test-script` 修复 `assert_rejected` 返回契约。
  3. 若 TC-ADDR-009 确认为产品缺陷，将状态改为“新建”，按 S3/P2 提交。
  4. 重跑并更新测试报告。

"""版本化配置加载器。

加载优先级（越具体越优先，后者覆盖前者）：
    base.yaml                  → 通用默认值
    <module>/<feature>.yaml   → 模块通用配置
    <module>/carriers/<carrier>.yaml      → 承运商覆盖（可选）
    <module>/carriers/<carrier>/<version>.yaml  → 版本覆盖（可选）

用法：
    # 1. 加载基础配置（全局，fixture 用）
    cfg = get_config()
    cfg["database"]["host"]          # 从 base.yaml 来

    # 2. 加载模块+功能配置（address_validation 无承运商差异）
    addr_cfg = get_module_config("lsp_backend", "address_validation")
    addr_cfg["expected"]["http_status"]["ok"]   # 200

    # 3. 加载承运商+版本配置（继承 pricing.yaml）
    cara_v2_cfg = get_module_config("lsp_quote", "pricing", carrier="carrier_a", version="v2.0")
    cara_v2_cfg["volumetric_coefficient"]        # 4000（v2.0 覆盖 v1.2 的 5000）
    cara_v2_cfg["api_timeout"]                   # 20（承运商覆盖 base 的 30）
    cara_v2_cfg["base_fee"]                      # 8.50（从 v1.2 继承）
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent
BASE_FILE = CONFIG_DIR / "base.yaml"

# 兼容旧路径（env.yaml 仍存在时优先用它，否则用 base.yaml）
# 这样旧测试不受影响，逐步迁移
_LEGACY_ENV_FILE = CONFIG_DIR / "env.yaml"


class ConfigError(RuntimeError):
    """配置文件缺失或结构错误时抛出。"""


# ──────────────────────────────────────────────────────────
# 深度合并
# ──────────────────────────────────────────────────────────

def deep_merge(base: dict, override: dict) -> dict:
    """override 覆盖 base；嵌套 dict 递归合并，不是整棵替换。"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Configuration root must be a mapping: {path}")
    return data


# ──────────────────────────────────────────────────────────
# 基础配置
# ──────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    """返回合并好的基础配置。

    优先：env.yaml（旧版，兼容） > base.yaml（新版）。
    这样渐进式迁移不会断。
    """
    if _LEGACY_ENV_FILE.is_file():
        return _load_yaml(_LEGACY_ENV_FILE)

    if not BASE_FILE.is_file():
        raise ConfigError(
            f"Configuration file not found. Expected either "
            f"{_LEGACY_ENV_FILE} or {BASE_FILE}"
        )

    data = _load_yaml(BASE_FILE)
    # 展开 services[env] → api_base_url（向后兼容旧 key）
    env = data.get("env", "local")
    services = data.get("services", {})
    if "api_base_url" not in data:
        # 取第一个非空服务地址作为默认（lsp_backend 是最常用的）
        for svc in ("lsp_backend", "lsp_quote", "lsp_booking"):
            url = services.get(svc, {}).get(env, "") if isinstance(services.get(svc), dict) else ""
            if url:
                data["api_base_url"] = url
                break
    return data


def get_value(path: str, default: Any = None, config: dict | None = None) -> Any:
    """读取点号分隔路径，如 'database.host'。"""
    node: Any = config if config is not None else get_config()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def get_required(path: str, config: dict | None = None) -> Any:
    """读取必填路径，缺失时抛 ConfigError。"""
    missing = object()
    value = get_value(path, default=missing, config=config)
    if value is missing:
        raise ConfigError(f"Missing required configuration key: {path}")
    return value


# ──────────────────────────────────────────────────────────
# 模块级配置（新增）
# ──────────────────────────────────────────────────────────

def get_module_config(
    module: str,
    feature: str | None = None,
    carrier: str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """按模块 → 承运商 → 版本层级加载配置，后者覆盖前者。

    查找顺序：
        1. base.yaml
        2. <module>/<feature>.yaml
        3. <module>/carrier/<carrier>.yaml           （可选）
        4. <module>/carrier/<carrier>/<version>.yaml （可选，承运商独有）
        5. <module>/carriers/<carrier>/<version>.yaml （兼容 carriers/ 目录）

    carrier 和 version 都传时才触发承运商版本覆盖。
    """
    merged = get_config()

    # Step 2: 模块功能配置
    if feature:
        feature_yaml = CONFIG_DIR / module / f"{feature}.yaml"
        merged = deep_merge(merged, _load_yaml(feature_yaml))

    # Step 3-5: 承运商 + 版本覆盖（carrier 必传）
    # 查找优先级（越具体越覆盖）：
    #   a) <module>/carrier/<carrier>.yaml           — carrier/ 子目录
    #   b) <module>/carriers/<carrier>.yaml          — carriers/ 复数子目录
    #   c) <module>/<carrier>/<version>.yaml         — 承运商目录直接在模块下（我们实际用的）
    #   d) <module>/carrier/<carrier>/<version>.yaml
    #   e) <module>/carriers/<carrier>/<version>.yaml
    if carrier:
        for sub in ("carrier", "carriers"):
            common = CONFIG_DIR / module / sub / f"{carrier}.yaml"
            if common.is_file():
                merged = deep_merge(merged, _load_yaml(common))

        if version:
            # 主路径：<module>/<carrier>/<version>.yaml（我们实际的结构）
            version_yaml = CONFIG_DIR / module / carrier / f"{version}.yaml"
            if not version_yaml.is_file():
                # 备用路径：carrier/ 和 carriers/ 子目录
                for sub in ("carrier", "carriers"):
                    alt = CONFIG_DIR / module / sub / carrier / f"{version}.yaml"
                    if alt.is_file():
                        version_yaml = alt
                        break
            if version_yaml.is_file():
                merged = deep_merge(merged, _load_yaml(version_yaml))

    return merged


def get_service_url(module: str, config: dict | None = None) -> str:
    """从 services[module][env] 取服务地址。空字符串表示本地 demo server。"""
    cfg = config if config is not None else get_config()
    env = cfg.get("env", "local")
    return cfg.get("services", {}).get(module, {}).get(env, "")


def list_carriers(module: str) -> list[str]:
    """列出某模块下所有承运商目录。

    查找优先级：<module>/carrier_a/ 直接在模块下 → carrier/ 和 carriers/ 子目录。
    """
    module_dir = CONFIG_DIR / module
    if not module_dir.is_dir():
        return []
    carriers = set()
    # 主路径：<module>/<carrier_name>/ 直接在模块下
    for child in module_dir.iterdir():
        if child.is_dir() and child.name not in ("carrier", "carriers", "lsp_backend", "lsp_quote", "lsp_booking"):
            # 看目录里有没有 yaml 文件（版本文件），有的话就是承运商目录
            if any(f.suffix == ".yaml" for f in child.iterdir()):
                carriers.add(child.name)
    # 备用：carrier/ 和 carriers/ 子目录
    for sub in ("carrier", "carriers"):
        vdir = module_dir / sub
        if vdir.is_dir():
            for d in vdir.iterdir():
                if d.is_dir():
                    carriers.add(d.name)
    return sorted(carriers)


def list_versions(module: str, carrier: str) -> list[str]:
    """列出某模块某承运商下所有可用版本。"""
    versions = set()
    # 主路径：<module>/<carrier>/
    main_dir = CONFIG_DIR / module / carrier
    if main_dir.is_dir():
        for f in main_dir.glob("*.yaml"):
            versions.add(f.stem)
    # 备用：carrier/ 和 carriers/ 子目录
    for sub in ("carrier", "carriers"):
        vdir = CONFIG_DIR / module / sub / carrier
        if vdir.is_dir():
            for f in vdir.glob("*.yaml"):
                versions.add(f.stem)
    return sorted(versions)

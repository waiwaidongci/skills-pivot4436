"""公开版本快照、版本差量和合作方交付包。

公开版本只保存"已公开"的键值集合：被抑制的格子不进入快照，因此修订时
撤下的格子只需在差量里标记移除，不会以"已抑制"字样覆盖旧值。
"""

import hashlib
import json

from .spec import SPEC

KIND_LABELS = {"full": "整表", "delta": "差量"}
OP_LABELS = {"set": "设置", "remove": "移除"}
_SUPPRESSED = "已抑制"
_PIVOT_TITLE = "渠道 × 培训项目"
PERIOD_KEY = SPEC["params"][0]["key"]
THRESHOLD_KEY = SPEC["params"][1]["key"]


def snapshot(result, params):
    """把一次复核通过的结果整理成可逐键比较的公开版本快照。"""
    cells = {
        f"param|{PERIOD_KEY}": params[PERIOD_KEY],
        f"param|{THRESHOLD_KEY}": params[THRESHOLD_KEY],
        "text|headline": result["headline"],
        "text|note": result.get("note", ""),
    }
    for metric in result.get("metrics", []):
        cells[f"metric|{metric['label']}"] = metric["value"]
        if metric.get("detail"):
            cells[f"metric_detail|{metric['label']}"] = metric["detail"]
    for table in result.get("tables", []):
        title = table["title"]
        columns = table["columns"]
        group_key, group_label = columns[0]["key"], columns[0]["label"]
        for row in table["rows"]:
            group = row.get(group_key, group_label)
            for column in columns[1:]:
                value = row.get(column["key"])
                if title == _PIVOT_TITLE and value == _SUPPRESSED:
                    # 抑制格不上公开表，撤下的格子不保留任何值。
                    continue
                cells[f"{title}|{group}|{column['label']}"] = value
    return {"period": params[PERIOD_KEY], "threshold": params[THRESHOLD_KEY],
            "headline": result["headline"], "note": result.get("note", ""),
            "cells": dict(sorted(cells.items()))}


def diff(baseline_cells, target_cells):
    """新增或改值的格子记设置，撤下的格子只记移除。"""
    operations = []
    for key in sorted(set(baseline_cells) | set(target_cells)):
        if key not in target_cells:
            operations.append({"op": "remove", "key": key})
        elif key not in baseline_cells or baseline_cells[key] != target_cells[key]:
            operations.append({"op": "set", "key": key, "value": target_cells[key]})
    return operations


def apply(cells, operations):
    """把交付包应用到基线格子；结果必须与目标版本逐键一致。"""
    merged = dict(cells)
    for operation in operations:
        key, kind = operation["key"], operation["op"]
        if kind == "set":
            merged[key] = operation["value"]
        elif kind == "remove":
            if key not in merged:
                raise ValueError(f"交付包与基线版本不一致，缺少单元格 {key}")
            del merged[key]
        else:
            raise ValueError("交付包含有无法识别的操作")
    return merged


def checksum(partner, baseline_version, target_version, kind, operations):
    raw = json.dumps({"partner": partner, "baseline": baseline_version, "target": target_version,
                      "kind": kind, "ops": operations},
                     ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def build(partner, baseline_version, baseline_snapshot, target_version, target_snapshot):
    """构造从基线版本到目标版本的交付包，并校验补齐后与目标版本一致。"""
    baseline_cells = (baseline_snapshot or {}).get("cells", {})
    target_cells = target_snapshot["cells"]
    kind = "full" if baseline_version == 0 else "delta"
    operations = diff(baseline_cells, target_cells)
    if apply(baseline_cells, operations) != target_cells:
        raise ValueError("交付包无法补齐到目标公开版本")
    return {"kind": kind, "operations": operations,
            "checksum": checksum(partner, baseline_version, target_version, kind, operations)}

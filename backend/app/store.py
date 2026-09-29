"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
跨模块联动（理赔提交后回写保单）通过 snapshot/restore 做一个最小事务：
联动中途抛错时整笔回滚，不会留下次数加了、状态却没更新的半成品。
"""
from __future__ import annotations

import contextlib
from copy import deepcopy
from typing import Any, Iterator

from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def next_id(self, module: str) -> int:
        return max((int(row.get("id", 0)) for row in self.rows(module)), default=0) + 1

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """最小事务：块内抛异常时把全部表恢复到进入前的快照。"""
        snapshot = deepcopy(self._tables)
        try:
            yield
        except Exception:
            self._tables = snapshot
            raise

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        # 在途理赔：理赔申请提交后保单次数与结案状态联动重算，
        # 这里始终按理赔表实时统计，状态一变概览数字就跟着变。
        ongoing_claims = sum(
            1 for row in self.rows("claim") if not row.get("closed")
        )
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
            {"label": "在途理赔数", "value": ongoing_claims},
        ]
        return {"cards": cards, "modules": modules}


store = Store()

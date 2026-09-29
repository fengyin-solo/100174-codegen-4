"""保险保单业务规则：登记、材料归档与理赔联动都收在这里。

保单本身不直接改“理赔次数/结案状态”——这两个字段由理赔服务在
提交申请、结案时通过 sync_from_claims 统一回算，避免两边口径不一致。
"""
from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "insurance"
REQUIRED_FIELDS = ["保单号", "承保单位", "投保设备", "保额"]


class InsuranceService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        insurer: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filter(
            keyword=keyword,
            status=status,
            insurer=insurer,
        )
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def _filter(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        insurer: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("保单号", ""))
                or keyword in str(row.get("投保设备", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if insurer:
            rows = [row for row in rows if insurer in str(row.get("承保单位", ""))]
        return rows

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def find_by_policy_no(self, policy_no: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("保单号", "")).strip() == policy_no.strip():
                return row
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        policy_no = str(values["保单号"]).strip()
        if self.find_by_policy_no(policy_no) is not None:
            return None, ["保单号重复，该保单已经登记过"]
        amount = _to_amount(values.get("保额"))
        if amount is None or amount <= 0:
            return None, ["保额需为大于 0 的数字"]

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {
            "id": store.next_id(MODULE),
            "保单号": policy_no,
            "承保单位": str(values["承保单位"]).strip(),
            "投保设备": str(values["投保设备"]).strip(),
            "保额": amount,
            "保费": _to_amount(values.get("保费")) or 0,
            "保险期限起": str(values.get("保险期限起") or "").strip(),
            "保险期限止": str(values.get("保险期限止") or "").strip(),
            "经办人": str(values.get("经办人") or "").strip(),
            "登记日期": datetime.now().strftime("%Y-%m-%d"),
            "理赔次数": 0,
            "结案状态": "无理赔",
            # 材料只追加不改写，登记时带的材料作为第一批历史材料归档。
            "保单材料": [],
            "status": "保障中",
            "pending": False,
            "abnormal": False,
        }
        rows.append(entry)
        return entry, []

    def add_material(
        self,
        entry_id: int,
        *,
        filename: str,
        category: str,
        content: bytes,
    ) -> tuple[dict[str, Any] | None, str]:
        """追加保单材料。历史材料永远保留，任何更新都不覆盖这张列表。"""
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"保单 {entry_id} 不存在或已归档"
        filename = filename.strip()
        if not filename:
            return None, "材料文件名不能为空"
        try:
            stored = content.decode("utf-8")
            encoding = "text"
        except UnicodeDecodeError:
            # 二进制材料用 base64 无损归档，导出时还原，历史材料不丢字节。
            stored = base64.b64encode(content).decode("ascii")
            encoding = "base64"
        material = {
            "name": filename,
            "category": category.strip() or "其他材料",
            "content": stored,
            "encoding": encoding,
            "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        entry.setdefault("保单材料", []).append(material)
        return material, f"材料「{filename}」已归档到保单 {entry.get('保单号')}"

    def sync_from_claims(self, policy: dict[str, Any]) -> None:
        """按理赔表实时回算保单的理赔次数、结案状态与在途标记。

        次数统计的是该保单项下全部理赔申请；结案状态区分在途与全结案。
        """
        policy_no = str(policy.get("保单号", ""))
        claims = [
            row
            for row in store.rows("claim")
            if str(row.get("保单号", "")) == policy_no
        ]
        policy["理赔次数"] = len(claims)
        ongoing = [row for row in claims if not row.get("closed")]
        if not claims:
            policy["结案状态"] = "无理赔"
        elif ongoing:
            policy["结案状态"] = "有在途理赔"
        else:
            policy["结案状态"] = "全部结案"
        # 保单自身的保障状态不因为理赔改变，在途标记单独驱动概览待处理量。
        policy["pending"] = bool(ongoing)


def _to_amount(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


insurance_service = InsuranceService()

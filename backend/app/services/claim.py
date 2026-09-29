"""理赔申请业务规则：提交联动保单、结案回算在途、材料包导出都收在这里。

联动口径：理赔申请提交/结案的同一笔事务里，按理赔表全量回算保单的
理赔次数、结案状态与在途标记，运营概览的在途理赔数同样实时统计，
因此从详情返回列表看到的次数一定是最新的。

导出口径：严格复用列表的筛选函数取“全部命中记录”，材料包里的条数、
申请金额合计与列表当前过滤范围逐条对得上；同一条件重复导出用相同
批次号覆盖旧包，绝不追加。
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.insurance import insurance_service
from app.store import store

MODULE = "claim"
REQUIRED_FIELDS = ["保单号", "事故设备", "出险日期", "申请金额", "事故经过"]
OPEN_STATUS = "理赔中"
CLOSED_STATUS = "已结案"

CSV_COLUMNS = [
    "理赔单号", "保单号", "承保单位", "事故设备", "出险日期",
    "申请金额", "申请人", "申请时间", "状态", "结案时间", "结案结论",
]


class ClaimService:
    # ---------- 查询 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        policy_no: str | None = None,
        insurer: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filter(
            keyword=keyword,
            status=status,
            policy_no=policy_no,
            insurer=insurer,
        )
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def summary(self, conditions: dict[str, Any]) -> dict[str, Any]:
        """按当前条件汇总：条数与合计与列表范围完全一致。"""
        rows = self._filter(
            keyword=conditions.get("keyword") or None,
            status=conditions.get("status") or None,
            policy_no=conditions.get("policy_no") or None,
            insurer=conditions.get("insurer") or None,
        )
        total_amount = round(sum(float(row.get("申请金额") or 0) for row in rows), 2)
        ongoing = sum(1 for row in rows if not row.get("closed"))
        return {"total": len(rows), "total_amount": total_amount, "ongoing": ongoing}

    def _filter(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        policy_no: str | None = None,
        insurer: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("理赔单号", ""))
                or keyword in str(row.get("保单号", ""))
                or keyword in str(row.get("事故设备", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if policy_no:
            rows = [row for row in rows if policy_no.strip() in str(row.get("保单号", ""))]
        if insurer:
            rows = [row for row in rows if insurer.strip() in str(row.get("承保单位", ""))]
        return rows

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ---------- 提交 / 结案 ----------
    def submit_claim(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"

        policy_no = str(values["保单号"]).strip()
        policy = insurance_service.find_by_policy_no(policy_no)
        if policy is None:
            return None, f"保单号 {policy_no} 未登记，请先登记保单再提交理赔"

        amount = _to_amount(values.get("申请金额"))
        if amount is None or amount <= 0:
            return None, "申请金额需为大于 0 的数字"
        if amount > float(policy.get("保额") or 0):
            return None, f"申请金额 {amount:g} 元超过保额 {float(policy['保额']):g} 元，请核对后重试"

        now = datetime.now()
        entry: dict[str, Any] = {
            "id": store.next_id(MODULE),
            "理赔单号": self._next_claim_no(now),
            "保单号": policy_no,
            "承保单位": str(policy.get("承保单位", "")),
            "事故设备": str(values["事故设备"]).strip(),
            "出险日期": str(values["出险日期"]).strip(),
            "申请金额": amount,
            "事故经过": str(values["事故经过"]).strip(),
            "申请人": str(values.get("申请人") or policy.get("经办人") or "").strip(),
            "结案结论": "",
            "申请时间": now.strftime("%Y-%m-%d %H:%M:%S"),
            "结案时间": "",
            "status": OPEN_STATUS,
            "pending": True,
            "abnormal": False,
            "closed": False,
        }
        try:
            with store.transaction():
                store.rows(MODULE).append(entry)
                # 保单的理赔次数与结案状态必须和申请一起更新，失败整笔回滚。
                insurance_service.sync_from_claims(policy)
        except Exception as exc:  # pragma: no cover - 联动异常兜底
            return None, f"理赔申请提交失败：{exc}，数据未更新，可重新提交"
        return entry, f"理赔申请 {entry['理赔单号']} 已提交，保单 {policy_no} 理赔次数已更新"

    def close_claim(self, entry_id: int, conclusion: str = "") -> tuple[dict[str, Any] | None, str]:
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"理赔单 {entry_id} 不存在或已归档"
        if entry.get("closed"):
            return None, f"理赔单 {entry.get('理赔单号')} 已结案，不能重复结案"
        policy = insurance_service.find_by_policy_no(str(entry.get("保单号", "")))
        now = datetime.now()
        try:
            with store.transaction():
                entry["status"] = CLOSED_STATUS
                entry["closed"] = True
                entry["pending"] = False
                entry["结案时间"] = now.strftime("%Y-%m-%d %H:%M:%S")
                entry["结案结论"] = conclusion.strip() or "承保单位已核定赔付，理赔结案。"
                if policy is not None:
                    # 结案同样回算：次数不变、在途减一、结案状态联动。
                    insurance_service.sync_from_claims(policy)
        except Exception as exc:  # pragma: no cover - 联动异常兜底
            return None, f"理赔结案失败：{exc}，数据未更新，可重试"
        return entry, f"理赔单 {entry['理赔单号']} 已结案，保单在途状态已重算"

    def _next_claim_no(self, now: datetime) -> str:
        prefix = f"CLM-{now.year}-"
        seq = 1
        for row in store.rows(MODULE):
            no = str(row.get("理赔单号", ""))
            if no.startswith(prefix):
                try:
                    seq = max(seq, int(no[len(prefix):]) + 1)
                except ValueError:
                    continue
        return f"{prefix}{seq:04d}"

    # ---------- 材料包导出 ----------
    def export_package(self, conditions: dict[str, Any]) -> dict[str, Any]:
        """按当前条件取全部命中记录打包；同条件重复导出覆盖旧包。"""
        normalized = {
            key: str(value).strip()
            for key, value in conditions.items()
            if str(value or "").strip()
        }
        rows = self._filter(
            keyword=normalized.get("keyword") or None,
            status=normalized.get("status") or None,
            policy_no=normalized.get("policy_no") or None,
            insurer=normalized.get("insurer") or None,
        )
        if not rows:
            raise ValueError("当前条件下没有命中的理赔申请，请调整筛选条件后再导出")

        total = len(rows)
        total_amount = round(sum(float(row.get("申请金额") or 0) for row in rows), 2)
        now = datetime.now()
        batch_id = self._batch_id(normalized)
        filename = f"理赔材料包_{batch_id}.zip"

        export_dir = settings.export_dir
        export_dir.mkdir(parents=True, exist_ok=True)
        package_path = export_dir / filename

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
            package.writestr(
                "理赔清单.csv",
                self._build_csv(rows, total, total_amount, normalized, now),
            )
            used_names: set[str] = set()
            for row in rows:
                policy = insurance_service.find_by_policy_no(str(row.get("保单号", "")))
                materials = list(policy.get("保单材料", [])) if policy else []
                folder = f"保单材料/{row.get('保单号')}-{row.get('理赔单号')}"
                for material in materials:
                    arcname = _unique_arcname(
                        f"{folder}/{material.get('name', '材料')}", used_names
                    )
                    stored = str(material.get("content", ""))
                    if material.get("encoding") == "base64":
                        data = base64.b64decode(stored)
                    else:
                        data = stored.encode("utf-8")
                    info = zipfile.ZipInfo(arcname, date_time=now.timetuple()[:6])
                    package.writestr(info, data)
                # 理赔申请本身也留一份说明，线下提交时能对应到保单材料。
                package.writestr(
                    _unique_arcname(f"{folder}/理赔申请说明.txt", used_names),
                    self._build_claim_note(row),
                )
            package.writestr(
                "导出说明.txt",
                self._build_readme(rows, total, total_amount, normalized, now, batch_id),
            )
            package.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "batch_id": batch_id,
                        "exported_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "conditions": normalized,
                        "total": total,
                        "total_amount": total_amount,
                        "claim_no_list": [row.get("理赔单号") for row in rows],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )

        # 同一批条件对应固定文件名：直接重写，旧包被覆盖而不是追加。
        overwritten = package_path.exists()
        package_path.write_bytes(buffer.getvalue())

        return {
            "ok": True,
            "message": (
                f"已覆盖旧材料包，本次按当前条件导出 {total} 条理赔申请，"
                f"申请金额合计 {total_amount:.2f} 元"
                if overwritten
                else f"已按当前条件导出 {total} 条理赔申请，申请金额合计 {total_amount:.2f} 元"
            ),
            "batch_id": batch_id,
            "filename": filename,
            "total": total,
            "total_amount": total_amount,
            "conditions": normalized,
            "exported_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "overwritten": overwritten,
            "path": str(package_path),
        }

    def locate_package(self, batch_id: str) -> Path | None:
        safe = batch_id.replace("/", "").replace("\\", "").replace("..", "")
        path = settings.export_dir / f"理赔材料包_{safe}.zip"
        return path if path.is_file() else None

    def _batch_id(self, normalized: dict[str, str]) -> str:
        raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
        # 无条件全量导出固定叫 all；带条件的用短哈希区分批次。
        return "all" if not normalized else f"筛选-{digest}"

    def _build_csv(
        self,
        rows: list[dict[str, Any]],
        total: int,
        total_amount: float,
        conditions: dict[str, str],
        now: datetime,
    ) -> bytes:
        buffer = io.StringIO()
        buffer.write(
            f"# 理赔清单（导出时间 {now.strftime('%Y-%m-%d %H:%M:%S')}；"
            f"筛选条件 {conditions or '全部'}）\n"
        )
        writer = csv.writer(buffer)
        writer.writerow(CSV_COLUMNS)
        for row in rows:
            writer.writerow([
                row.get("理赔单号", ""),
                row.get("保单号", ""),
                row.get("承保单位", ""),
                row.get("事故设备", ""),
                row.get("出险日期", ""),
                f"{float(row.get('申请金额') or 0):.2f}",
                row.get("申请人", ""),
                row.get("申请时间", ""),
                "已结案" if row.get("closed") else "理赔中",
                row.get("结案时间", ""),
                row.get("结案结论", ""),
            ])
        writer.writerow([])
        writer.writerow(["合计条数", total])
        writer.writerow(["申请金额合计", f"{total_amount:.2f}"])
        # utf-8-sig 让 Excel 直接打开不乱码。
        return buffer.getvalue().encode("utf-8-sig")

    def _build_readme(
        self,
        rows: list[dict[str, Any]],
        total: int,
        total_amount: float,
        conditions: dict[str, str],
        now: datetime,
        batch_id: str,
    ) -> str:
        lines = [
            "理赔材料包（线下提交用）",
            f"导出批次：{batch_id}",
            f"导出时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
            f"筛选条件：{conditions or '全部'}",
            f"理赔条数：{total}",
            f"申请金额合计：{total_amount:.2f} 元",
            "文件说明：",
            "  理赔清单.csv —— 当前条件下全部命中的理赔申请及合计",
            "  保单材料/    —— 每条理赔对应保单的历史材料，只追加不删除",
            "  manifest.json —— 批次指纹与条数合计，供系统核对",
            "",
            "本次包含的理赔单：",
        ]
        for row in rows:
            lines.append(
                f"  {row.get('理赔单号')}｜{row.get('保单号')}｜"
                f"{row.get('承保单位')}｜{float(row.get('申请金额') or 0):.2f} 元｜"
                f"{'已结案' if row.get('closed') else '理赔中'}"
            )
        return "\n".join(lines)

    def _build_claim_note(self, row: dict[str, Any]) -> bytes:
        lines = [
            f"理赔单号：{row.get('理赔单号', '')}",
            f"保单号：{row.get('保单号', '')}",
            f"承保单位：{row.get('承保单位', '')}",
            f"事故设备：{row.get('事故设备', '')}",
            f"出险日期：{row.get('出险日期', '')}",
            f"申请金额：{float(row.get('申请金额') or 0):.2f} 元",
            f"申请人：{row.get('申请人', '')}",
            f"申请时间：{row.get('申请时间', '')}",
            f"状态：{'已结案' if row.get('closed') else '理赔中'}",
            f"结案时间：{row.get('结案时间', '')}",
            f"结案结论：{row.get('结案结论', '')}",
            "",
            "事故经过：",
            str(row.get("事故经过", "")),
        ]
        return "\n".join(lines).encode("utf-8")


def _to_amount(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _unique_arcname(name: str, used: set[str]) -> str:
    """同名材料去重：保留历史材料的同时避免包内路径覆盖。"""
    if name not in used:
        used.add(name)
        return name
    parent = str(Path(name).parent)
    stem = Path(name).stem
    suffix = Path(name).suffix
    counter = 2
    while True:
        candidate = f"{parent}/{stem}({counter}){suffix}" if parent != "." else f"{stem}({counter}){suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


claim_service = ClaimService()

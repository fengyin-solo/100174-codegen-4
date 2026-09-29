"""保险与理赔业务规则：保单登记、理赔申请、状态流转、在途统计与打包导出。

理赔申请从属于保单，单独放在 insurance_claim 子表里；提交理赔后保单的理赔次数与
结案状态一起重算，历史保单字段只做增量更新，不会丢材料。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "insurance"
CLAIM_MODULE = "insurance_claim"
REQUIRED_FIELDS = ["保单号", "承保单位", "保额"]
POLICY_STATUSES = ["保障中", "已失效"]
CLAIM_STATUSES = ["待受理", "审核中", "已赔付", "已结案", "已驳回"]
# 在途理赔：尚未结案或驳回的申请单。
IN_TRANSIT_STATUSES = {"待受理", "审核中", "已赔付"}
CLAIM_ACTIONS = {"受理": "审核中", "赔付": "已赔付", "结案": "已结案", "驳回": "已驳回"}
POLICY_ACTIONS = {"退保": "已失效"}


def _to_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class InsuranceService:
    # ---------- 保单 ----------
    def list_policies(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("保单号", "")) or keyword in str(row.get("承保单位", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_policy(self, policy_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, policy_id)

    def create_policy(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        coverage = _to_number(values.get("保额"))
        if coverage is None or coverage < 0:
            return None, ["保额必须是不小于 0 的数字"]
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["保单号"] = str(values.get("保单号") or "").strip()
        entry["承保单位"] = str(values.get("承保单位") or "").strip()
        entry["保额"] = coverage
        entry["险种"] = str(values.get("险种") or "").strip() or "—"
        entry["保险期间"] = str(values.get("保险期间") or "").strip() or "—"
        entry["status"] = POLICY_STATUSES[0]
        entry["理赔次数"] = 0
        entry["结案状态"] = "未结案"
        entry["pending"] = False
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_policy_action(self, policy_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        policy = store.find(MODULE, policy_id)
        if policy is None:
            return None, f"保单 {policy_id} 不存在或已归档"
        if action not in POLICY_ACTIONS:
            return None, f"动作「{action}」不属于保单可执行范围"
        target = POLICY_ACTIONS[action]
        policy["status"] = target
        policy["pending"] = False
        return policy, f"保单已{action}"

    # ---------- 理赔申请 ----------
    def list_claims(self, policy_id: int) -> tuple[list[dict[str, Any]] | None, str | None]:
        policy = store.find(MODULE, policy_id)
        if policy is None:
            return None, f"保单 {policy_id} 不存在或已归档"
        policy_no = str(policy.get("保单号") or "")
        rows = [row for row in store.rows(CLAIM_MODULE) if str(row.get("关联保单") or "") == policy_no]
        return rows, None

    def create_claim(self, policy_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        policy = store.find(MODULE, policy_id)
        if policy is None:
            return None, f"保单 {policy_id} 不存在或已归档"
        missing = [field for field in ["理赔单号", "理赔金额"] if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        amount = _to_number(values.get("理赔金额"))
        if amount is None or amount <= 0:
            return None, "理赔金额必须是大于 0 的数字"
        claim_no = str(values.get("理赔单号") or "").strip()
        if any(str(row.get("理赔单号") or "") == claim_no for row in store.rows(CLAIM_MODULE)):
            return None, f"理赔单号 {claim_no} 已存在，不能重复登记"
        rows = store.rows(CLAIM_MODULE)
        claim: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        claim["理赔单号"] = claim_no
        claim["关联保单"] = str(policy.get("保单号") or "")
        claim["理赔金额"] = amount
        claim["申请日期"] = str(values.get("申请日期") or "").strip() or _now()
        claim["理赔说明"] = str(values.get("理赔说明") or "").strip() or "—"
        claim["status"] = CLAIM_STATUSES[0]
        claim["in_transit"] = True
        claim["abnormal"] = False
        rows.append(claim)
        # 提交理赔后立刻重算保单的理赔次数与结案状态，历史字段不动。
        self._recompute_policy(policy)
        return claim, None

    def run_claim_action(self, claim_id: int, action: str) -> tuple[dict[str, Any] | None, str | None]:
        claim = store.find(CLAIM_MODULE, claim_id)
        if claim is None:
            return None, f"理赔申请 {claim_id} 不存在或已归档"
        if action not in CLAIM_ACTIONS:
            return None, f"动作「{action}」不属于理赔申请可执行范围"
        target = CLAIM_ACTIONS[action]
        claim["status"] = target
        claim["in_transit"] = target in IN_TRANSIT_STATUSES
        policy = self._find_policy_by_no(str(claim.get("关联保单") or ""))
        if policy is not None:
            self._recompute_policy(policy)
        return claim, f"理赔申请已{action}"

    def _find_policy_by_no(self, policy_no: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("保单号") or "") == policy_no:
                return row
        return None

    def _recompute_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        policy_no = str(policy.get("保单号") or "")
        claims = [row for row in store.rows(CLAIM_MODULE) if str(row.get("关联保单") or "") == policy_no]
        in_transit = [row for row in claims if row.get("in_transit")]
        policy["理赔次数"] = len(claims)
        policy["结案状态"] = "未结案" if in_transit else "已结案"
        policy["pending"] = bool(in_transit)
        return policy

    # ---------- 统计与打包导出 ----------
    def summarize(self, *, keyword: str | None = None, status: str | None = None) -> dict[str, Any]:
        """按当前过滤范围统计保单与理赔的条数、合计，供列表与打包文件对账。"""
        items, total = self.list_policies(keyword=keyword, status=status, page=1, size=10000)
        all_claims: list[dict[str, Any]] = []
        for policy in items:
            policy_no = str(policy.get("保单号") or "")
            all_claims.extend(
                row for row in store.rows(CLAIM_MODULE) if str(row.get("关联保单") or "") == policy_no
            )
        return {
            "policy_count": total,
            "claim_count": len(all_claims),
            "total_coverage": sum(_to_number(row.get("保额")) or 0 for row in items),
            "total_claim_amount": sum(_to_number(row.get("理赔金额")) or 0 for row in all_claims),
            "in_transit_count": sum(1 for row in all_claims if row.get("in_transit")),
        }

    def build_export(self, *, keyword: str | None = None, status: str | None = None) -> dict[str, Any]:
        """把当前过滤范围内的理赔申请连同保单材料打成一个文件包。

        批次号由过滤条件决定：同一批条件重复导出批次号不变，直接覆盖旧包而不是追加。
        """
        items, total = self.list_policies(keyword=keyword, status=status, page=1, size=10000)
        policies: list[dict[str, Any]] = []
        all_claims: list[dict[str, Any]] = []
        for policy in items:
            policy_no = str(policy.get("保单号") or "")
            claims = [row for row in store.rows(CLAIM_MODULE) if str(row.get("关联保单") or "") == policy_no]
            # 复制一份再挂理赔子表，避免导出结构污染内存里的保单记录。
            policies.append({**policy, "claims": claims})
            all_claims.extend(claims)
        summary = self.summarize(keyword=keyword, status=status)
        sig = f"{keyword or ''}|{status or ''}"
        batch_no = "INS-" + hashlib.md5(sig.encode("utf-8")).hexdigest()[:8].upper()
        package = {
            "package": "insurance_claims_package",
            "batch_no": batch_no,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "filters": {"keyword": keyword or "", "status": status or ""},
            "summary": summary,
            "policies": policies,
            "claims": all_claims,
        }
        store.save_package(batch_no, package)
        return package

    def list_packages(self) -> list[dict[str, Any]]:
        return store.list_packages()

    def get_package(self, batch_no: str) -> dict[str, Any] | None:
        return store.get_package(batch_no)

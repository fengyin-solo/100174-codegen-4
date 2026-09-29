"""保险与理赔接口：保单登记、理赔申请、状态流转、在途统计与打包导出。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.insurance import InsuranceService

router = APIRouter(prefix="/api/insurance", tags=["保险与理赔"])

service = InsuranceService()

LIST_FIELDS = ["保单号", "承保单位", "保额", "险种", "理赔次数", "结案状态", "保单状态"]
POLICY_STATUSES = ["保障中", "已失效"]


@router.get("", response_model=PageResult[dict])
def list_policies(
    keyword: str | None = Query(default=None, description="按保单号或承保单位检索"),
    status: str | None = Query(default=None, description="保障中、已失效"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按保单号/承保单位与状态过滤保单列表；合计口径与打包导出保持一致。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_policies(keyword=keyword, status=status, page=page, size=size)
    summary = service.summarize(keyword=keyword, status=status)
    return PageResult(items=items, total=total, page=page, size=size, summary=summary)


@router.post("", response_model=ActionResult)
def create_policy(payload: EntryPayload) -> ActionResult:
    """登记一条保单，缺字段或保额不合法时说明原因而不是静默丢弃。"""
    entry, missing = service.create_policy(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="保单已登记", entry=entry)


@router.post("/export", response_model=ActionResult)
def export_package(
    keyword: str | None = Query(default=None, description="按保单号或承保单位检索"),
    status: str | None = Query(default=None, description="保障中、已失效"),
) -> ActionResult:
    """按当前过滤条件把理赔申请连同保单材料打成一个文件包。

    同一批条件重复导出会覆盖旧包；接口失败时返回原因，前端可凭批次重新导出。
    """
    package = service.build_export(keyword=keyword, status=status)
    summary = package["summary"]
    return ActionResult(
        ok=True,
        message=(
            f"打包完成：{summary['policy_count']} 张保单、{summary['claim_count']} 条理赔申请，"
            f"保额合计 {summary['total_coverage']:.2f} 元，理赔合计 {summary['total_claim_amount']:.2f} 元"
        ),
        entry={
            "batch_no": package["batch_no"],
            "file_name": f"保险理赔打包_{package['batch_no']}.json",
            "exported_at": package["exported_at"],
            "summary": summary,
        },
    )


@router.get("/packages")
def list_packages() -> dict[str, Any]:
    """列出已生成的打包文件包，供前端展示与下载。"""
    packages = service.list_packages()
    return {
        "items": [
            {
                "batch_no": package["batch_no"],
                "file_name": f"保险理赔打包_{package['batch_no']}.json",
                "exported_at": package["exported_at"],
                "filters": package["filters"],
                "summary": package["summary"],
            }
            for package in packages
        ]
    }


@router.get("/packages/{batch_no}/download")
def download_package(batch_no: str) -> Response:
    """下载指定批次的打包文件；批次不存在（已被覆盖或未生成）时给出可读说明。"""
    package = service.get_package(batch_no)
    if package is None:
        raise HTTPException(status_code=404, detail=f"打包文件 {batch_no} 不存在或已被覆盖，请重新导出")
    content = json.dumps(package, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="insurance_package_{batch_no}.json"'},
    )


@router.get("/{policy_id}", response_model=dict)
def get_policy(policy_id: int) -> dict:
    """读取单条保单明细；不存在时给出可读的错误说明。"""
    entry = service.get_policy(policy_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"保单 {policy_id} 不存在或已归档")
    return entry


@router.post("/{policy_id}/actions", response_model=ActionResult)
def run_policy_action(policy_id: int, payload: EntryPayload) -> ActionResult:
    """对保单执行退保等动作；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_policy_action(policy_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/{policy_id}/claims")
def list_claims(policy_id: int) -> dict[str, Any]:
    """读取某张保单下的理赔申请记录。"""
    rows, message = service.list_claims(policy_id)
    if rows is None:
        raise HTTPException(status_code=404, detail=message)
    return {"items": rows, "total": len(rows)}


@router.post("/{policy_id}/claims", response_model=ActionResult)
def create_claim(policy_id: int, payload: EntryPayload) -> ActionResult:
    """提交一条理赔申请；成功后保单的理赔次数与结案状态一并更新。"""
    entry, message = service.create_claim(policy_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="理赔申请已提交，保单理赔次数与结案状态已更新", entry=entry)


@router.post("/claims/{claim_id}/actions", response_model=ActionResult)
def run_claim_action(claim_id: int, payload: EntryPayload) -> ActionResult:
    """对理赔申请执行受理、赔付、结案、驳回；结案后保单结案状态跟着重算。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_claim_action(claim_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

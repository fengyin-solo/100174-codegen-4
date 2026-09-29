"""理赔申请接口：提交联动保单、结案回算在途、材料包打包导出与下载。

导出口径与列表完全一致：同一组筛选条件先过滤，再按“全部命中记录”打包，
返回的条数、申请金额合计即列表当前范围的数字。同条件重复导出覆盖旧包。
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.schemas import ActionResult, EntryPayload, ExportPackageResult, PageResult
from app.services.claim import claim_service

router = APIRouter(prefix="/api/claim", tags=["理赔申请"])

LIST_FIELDS = ["理赔单号", "保单号", "承保单位", "事故设备", "出险日期", "申请金额", "申请人", "申请时间", "结案时间", "结案结论"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按理赔单号、保单号、事故设备检索"),
    status: str | None = Query(default=None, description="理赔中、已结案"),
    policy_no: str | None = Query(default=None, description="按保单号过滤"),
    insurer: str | None = Query(default=None, description="按承保单位过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按当前条件读取理赔申请列表；导出与这里使用同一套筛选口径。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = claim_service.list_entries(
        keyword=keyword,
        status=status,
        policy_no=policy_no,
        insurer=insurer,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary", response_model=dict)
def summary(
    keyword: str | None = None,
    status: str | None = None,
    policy_no: str | None = None,
    insurer: str | None = None,
) -> dict:
    """当前条件下的条数与申请金额合计，供列表和导出包对账。"""
    return claim_service.summary(
        {"keyword": keyword, "status": status, "policy_no": policy_no, "insurer": insurer}
    )


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条理赔申请明细；不存在时给出可读的错误说明。"""
    entry = claim_service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"理赔单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def submit_claim(payload: EntryPayload) -> ActionResult:
    """提交理赔申请：保单理赔次数、结案状态同事务联动更新，失败说明原因可重试。"""
    entry, message = claim_service.submit_claim(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对理赔单执行结案；已结案的单据会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    if action != "确认结案":
        return ActionResult(ok=False, message=f"动作「{action}」不属于理赔申请可执行范围")
    conclusion = str(payload.values.get("结案结论") or "")
    entry, message = claim_service.close_claim(entry_id, conclusion)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/export", response_model=ExportPackageResult)
def export_package(
    keyword: str | None = None,
    status: str | None = None,
    policy_no: str | None = None,
    insurer: str | None = None,
) -> ExportPackageResult:
    """按当前条件取全部命中记录打包成一份材料文件；失败返回原因，可直接重试。"""
    conditions = {
        "keyword": keyword or "",
        "status": status or "",
        "policy_no": policy_no or "",
        "insurer": insurer or "",
    }
    try:
        result = claim_service.export_package(conditions)
    except ValueError as exc:
        # 业务可预期失败：返回 200 + ok=False，前端就地说明并保留重试按钮。
        return ExportPackageResult(ok=False, message=str(exc))
    except OSError as exc:
        return ExportPackageResult(ok=False, message=f"材料包写入磁盘失败：{exc}，请重试")
    return ExportPackageResult(**{k: v for k, v in result.items() if k != "path"})


@router.get("/export/{batch_id}/download")
def download_package(batch_id: str) -> FileResponse:
    """下载已生成的材料包；旧包已被同条件导出覆盖时拿到的就是最新一份。"""
    path = claim_service.locate_package(batch_id)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="该批次材料包不存在或已被清理，请重新点击导出后再下载",
        )
    filename = path.name
    quoted = quote(filename)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quoted}"},
    )

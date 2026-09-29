"""保险保单接口：登记保单号、承保单位、保额与保单材料，材料只追加不丢失。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.insurance import insurance_service

router = APIRouter(prefix="/api/insurance", tags=["保险保单"])

LIST_FIELDS = ["保单号", "承保单位", "投保设备", "保额", "保费", "保险期限起", "保险期限止", "经办人", "登记日期", "理赔次数", "结案状态"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按保单号、投保设备检索"),
    status: str | None = Query(default=None, description="保障中、已到期"),
    insurer: str | None = Query(default=None, description="按承保单位检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按保单号、承保单位与状态过滤保单；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = insurance_service.list_entries(
        keyword=keyword, status=status, insurer=insurer, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取保单明细（含历史材料与最新理赔次数）；不存在时给出可读说明。"""
    entry = insurance_service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"保单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一张保单，缺字段或保单号重复时说明原因，允许修正后重试。"""
    entry, problems = insurance_service.create_entry(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message=f"保单 {entry['保单号']} 已登记", entry=entry)


@router.post("/{entry_id}/materials", response_model=ActionResult)
async def add_material(
    entry_id: int,
    request: Request,
    filename: str = Query(..., description="材料文件名"),
    category: str = Query(default="其他材料", description="材料类别"),
) -> ActionResult:
    """追加保单材料。直接接收原始字节，避免引入 multipart 依赖。"""
    body = await request.body()
    if not body:
        return ActionResult(ok=False, message="材料内容为空，未归档，请重新上传")
    material, message = insurance_service.add_material(
        entry_id, filename=filename, category=category, content=body
    )
    if material is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=material)

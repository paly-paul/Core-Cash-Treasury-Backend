import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status, Response
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_permission
from core_cash_shared.schemas.auth import UserClaims
from core_cash_shared.enums import Permission
from app.database import get_db
from app.models.source_file import SourceFile
from app.models.ar_data import ARData
from app.models.ap_data import APData
from app.models.statement import Statement
from app.services.cache import invalidate_cash_position_cache
from app.services.csv_parsers.bank_balance_parser import BankBalanceParser
from app.services.csv_parsers.ar_parser import ARParser
from app.services.csv_parsers.ap_parser import APParser
from app.jobs.interface import JobPublisher
from core_cash_shared import JobEnvelope, JobType
from core_cash_shared.error_codes import (
    VALIDATION_EMPTY_FILE,
    VALIDATION_FILE_TOO_LARGE,
    VALIDATION_UNSUPPORTED_FORMAT,
    VALIDATION_MISSING_COLUMN,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class JobPublisherImpl(JobPublisher):
    def __init__(self, db: AsyncSession):
        self.db = db

    async def publish(self, job: JobEnvelope) -> str:
        from app.jobs.in_process import InProcessJobPublisher
        publisher = InProcessJobPublisher(self.db)
        return await publisher.publish(job)


@router.post("/api/files/upload")
async def upload_bank_balances(
    file: UploadFile = File(...),
    column_mapping: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(get_current_user),
):
    if not current_user.has_permission(Permission.EDIT_ASSUMPTIONS):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Insufficient permissions"})

    client_id = current_user.client_id
    content = await file.read()

    try:
        BankBalanceParser.validate_file_format(file.filename, file.content_type)
        BankBalanceParser.validate_file_size(content)
    except Exception as e:
        error_code = getattr(e, 'code', 'VALIDATION_UNSUPPORTED_FORMAT')
        message = getattr(e, 'message', str(e))
        if error_code == VALIDATION_FILE_TOO_LARGE:
            raise HTTPException(status_code=413, detail={"code": error_code, "message": message})
        else:
            raise HTTPException(status_code=400, detail={"code": error_code, "message": message})

    column_mapping_dict = {}
    if column_mapping:
        try:
            column_mapping_dict = json.loads(column_mapping)
        except json.JSONDecodeError:
            pass

    try:
        parse_result = await BankBalanceParser.parse_and_store(
            content, client_id, file.filename, db, column_mapping_dict
        )
    except Exception as e:
        error_code = getattr(e, 'code', 'VALIDATION_UNSUPPORTED_FORMAT')
        message = getattr(e, 'message', str(e))
        if error_code == VALIDATION_EMPTY_FILE:
            raise HTTPException(status_code=400, detail={"code": error_code, "message": message})
        elif error_code == VALIDATION_MISSING_COLUMN:
            raise HTTPException(status_code=422, detail={"code": error_code, "message": message})
        else:
            raise HTTPException(status_code=400, detail={"code": error_code, "message": message})

    rows_valid = parse_result["rows_valid"]
    rows_failed = parse_result["rows_failed"]

    if rows_valid == 0 and rows_failed > 0:
        raise HTTPException(status_code=422, detail={
            "code": "VALIDATION_PARSE_FAILED",
            "message": "All rows failed validation",
            "rows_failed": rows_failed
        })

    source_file_record = SourceFile(
        client_id=client_id,
        user_id=current_user.id,
        file_name=file.filename,
        file_type="csv",
        upload_type="bank_balances",
        status="Processing" if rows_valid > 0 else "Failed",
        rows_received=parse_result["rows_received"],
        rows_valid=rows_valid,
        rows_failed=rows_failed,
        error_detail={"flagged_rows": parse_result["flagged_rows"]} if parse_result["flagged_rows"] else None,
        parsed_at=datetime.utcnow() if rows_valid > 0 else None,
    )

    db.add(source_file_record)
    await db.flush()

    for stmt_data in parse_result["statements"]:
        statement = Statement(
            account_id=stmt_data["account_id"],
            statement_date=stmt_data["statement_date"],
            closing_balance=stmt_data["closing_balance"],
            available_balance=stmt_data["available_balance"],
            currency=stmt_data["currency"],
            source=stmt_data["source"],
        )
        db.add(statement)

    await db.commit()

    if rows_valid > 0:
        await invalidate_cash_position_cache(str(client_id))

    response_status = 207 if rows_failed > 0 else 202

    return Response(
        content=json.dumps({
            "upload_id": str(source_file_record.id),
            "file_name": file.filename,
            "status": "Processing",
            "rows_received": parse_result["rows_received"],
            "rows_valid": rows_valid,
            "rows_flagged": parse_result["rows_flagged"],
            "flagged_rows": parse_result["flagged_rows"],
            "negative_balances_detected": parse_result["negative_balances_detected"],
            "negative_balance_accounts": parse_result["negative_balance_accounts"],
        }),
        status_code=response_status,
        media_type="application/json"
    )


@router.post("/api/files/upload/ar", status_code=202)
async def upload_ar(
    file: UploadFile = File(...),
    column_mapping: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(get_current_user),
):
    if not current_user.has_permission(Permission.EDIT_ASSUMPTIONS):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Insufficient permissions"})

    client_id = current_user.client_id
    content = await file.read()

    try:
        ARParser.validate_file_format(file.filename, file.content_type)
        ARParser.validate_file_size(content)
    except Exception as e:
        error_code = getattr(e, 'code', 'VALIDATION_UNSUPPORTED_FORMAT')
        message = getattr(e, 'message', str(e))
        if error_code == VALIDATION_FILE_TOO_LARGE:
            raise HTTPException(status_code=413, detail={"code": error_code, "message": message})
        else:
            raise HTTPException(status_code=400, detail={"code": error_code, "message": message})

    column_mapping_dict = {}
    if column_mapping:
        try:
            column_mapping_dict = json.loads(column_mapping)
        except json.JSONDecodeError:
            pass

    try:
        parse_result = await ARParser.parse_and_store(
            content, client_id, file.filename, db, column_mapping_dict
        )
    except Exception as e:
        error_code = getattr(e, 'code', 'VALIDATION_UNSUPPORTED_FORMAT')
        message = getattr(e, 'message', str(e))
        if error_code == VALIDATION_EMPTY_FILE:
            raise HTTPException(status_code=400, detail={"code": error_code, "message": message})
        elif error_code == VALIDATION_MISSING_COLUMN:
            raise HTTPException(status_code=422, detail={"code": error_code, "message": message})
        else:
            raise HTTPException(status_code=400, detail={"code": error_code, "message": message})

    rows_valid = parse_result["rows_valid"]
    rows_failed = parse_result["rows_failed"]

    if rows_valid == 0 and rows_failed > 0:
        raise HTTPException(status_code=422, detail={
            "code": "VALIDATION_PARSE_FAILED",
            "message": "All rows failed validation",
            "rows_failed": rows_failed
        })

    source_file_record = SourceFile(
        client_id=client_id,
        user_id=current_user.id,
        file_name=file.filename,
        file_type="csv",
        upload_type="ar",
        status="Completed" if rows_valid > 0 else "Failed",
        rows_received=parse_result["rows_received"],
        rows_valid=rows_valid,
        rows_failed=rows_failed,
        error_detail={"flagged_rows": parse_result["flagged_rows"]} if parse_result["flagged_rows"] else None,
        parsed_at=datetime.utcnow() if rows_valid > 0 else None,
    )

    db.add(source_file_record)
    await db.flush()

    for ar_data in parse_result["ar_rows"]:
        ar = ARData(
            client_id=ar_data["client_id"],
            source_file_id=source_file_record.id,
            entity_id=ar_data["entity_id"],
            counterparty_name=ar_data["counterparty_name"],
            invoice_number=ar_data["invoice_number"],
            invoice_date=ar_data["invoice_date"],
            due_date=ar_data["due_date"],
            currency=ar_data["currency"],
            amount_local=ar_data["amount_local"],
            status=ar_data["status"],
        )
        db.add(ar)

    await db.commit()

    return {
        "upload_id": str(source_file_record.id),
        "file_name": file.filename,
        "status": "Completed",
        "rows_received": parse_result["rows_received"],
        "rows_valid": rows_valid,
        "rows_flagged": parse_result["rows_flagged"],
    }


@router.post("/api/files/upload/ap", status_code=202)
async def upload_ap(
    file: UploadFile = File(...),
    column_mapping: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(get_current_user),
):
    if not current_user.has_permission(Permission.EDIT_ASSUMPTIONS):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Insufficient permissions"})

    client_id = current_user.client_id
    content = await file.read()

    try:
        APParser.validate_file_format(file.filename, file.content_type)
        APParser.validate_file_size(content)
    except Exception as e:
        error_code = getattr(e, 'code', 'VALIDATION_UNSUPPORTED_FORMAT')
        message = getattr(e, 'message', str(e))
        if error_code == VALIDATION_FILE_TOO_LARGE:
            raise HTTPException(status_code=413, detail={"code": error_code, "message": message})
        else:
            raise HTTPException(status_code=400, detail={"code": error_code, "message": message})

    column_mapping_dict = {}
    if column_mapping:
        try:
            column_mapping_dict = json.loads(column_mapping)
        except json.JSONDecodeError:
            pass

    try:
        parse_result = await APParser.parse_and_store(
            content, client_id, file.filename, db, column_mapping_dict
        )
    except Exception as e:
        error_code = getattr(e, 'code', 'VALIDATION_UNSUPPORTED_FORMAT')
        message = getattr(e, 'message', str(e))
        if error_code == VALIDATION_EMPTY_FILE:
            raise HTTPException(status_code=400, detail={"code": error_code, "message": message})
        elif error_code == VALIDATION_MISSING_COLUMN:
            raise HTTPException(status_code=422, detail={"code": error_code, "message": message})
        else:
            raise HTTPException(status_code=400, detail={"code": error_code, "message": message})

    rows_valid = parse_result["rows_valid"]
    rows_failed = parse_result["rows_failed"]

    if rows_valid == 0 and rows_failed > 0:
        raise HTTPException(status_code=422, detail={
            "code": "VALIDATION_PARSE_FAILED",
            "message": "All rows failed validation",
            "rows_failed": rows_failed
        })

    source_file_record = SourceFile(
        client_id=client_id,
        user_id=current_user.id,
        file_name=file.filename,
        file_type="csv",
        upload_type="ap",
        status="Completed" if rows_valid > 0 else "Failed",
        rows_received=parse_result["rows_received"],
        rows_valid=rows_valid,
        rows_failed=rows_failed,
        error_detail={"flagged_rows": parse_result["flagged_rows"]} if parse_result["flagged_rows"] else None,
        parsed_at=datetime.utcnow() if rows_valid > 0 else None,
    )

    db.add(source_file_record)
    await db.flush()

    for ap_data in parse_result["ap_rows"]:
        ap = APData(
            client_id=ap_data["client_id"],
            source_file_id=source_file_record.id,
            entity_id=ap_data["entity_id"],
            vendor_name=ap_data["vendor_name"],
            invoice_number=ap_data["invoice_number"],
            invoice_date=ap_data["invoice_date"],
            due_date=ap_data["due_date"],
            currency=ap_data["currency"],
            amount_local=ap_data["amount_local"],
            category=ap_data["category"],
        )
        db.add(ap)

    await db.commit()

    if rows_valid > 0:
        try:
            job = JobEnvelope(
                job_type=JobType.FORECAST,
                client_id=str(client_id),
                user_id=str(current_user.id),
                payload={"triggered_by": "ap_upload"},
            )
            publisher = JobPublisherImpl(db)
            await publisher.publish(job)
        except Exception as e:
            logger.error(f"Failed to publish forecast job for AP upload: {e}")

    return {
        "upload_id": str(source_file_record.id),
        "file_name": file.filename,
        "status": "Completed",
        "rows_received": parse_result["rows_received"],
        "rows_valid": rows_valid,
        "rows_flagged": parse_result["rows_flagged"],
    }


@router.get("/api/files", status_code=200)
async def get_uploads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    upload_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(get_current_user),
):
    client_id = current_user.client_id

    query = select(SourceFile).where(SourceFile.client_id == client_id)

    if upload_type:
        query = query.where(SourceFile.upload_type == upload_type)

    query = query.order_by(desc(SourceFile.created_at))

    result = await db.execute(query)
    total = len(result.scalars().all())

    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)
    uploads = result.scalars().all()

    uploads_response = []
    for upload in uploads:
        result_user = await db.execute(
            select(UserModel).where(UserModel.id == upload.user_id)
        )
        user = result_user.scalar_one_or_none()
        uploads_response.append({
            "upload_id": str(upload.id),
            "file_name": upload.file_name,
            "file_type": upload.file_type,
            "upload_type": upload.upload_type,
            "status": upload.status,
            "rows_processed": upload.rows_received,
            "rows_valid": upload.rows_valid,
            "uploaded_by": user.email if user else "Unknown",
            "uploaded_at": upload.created_at.isoformat() if upload.created_at else None,
            "parsed_at": upload.parsed_at.isoformat() if upload.parsed_at else None,
        })

    return {
        "uploads": uploads_response,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/api/files/{upload_id}/status", status_code=200)
async def get_upload_status(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(get_current_user),
):
    client_id = current_user.client_id

    result = await db.execute(
        select(SourceFile).where(
            and_(SourceFile.id == upload_id, SourceFile.client_id == client_id)
        )
    )
    upload = result.scalar_one_or_none()

    if not upload:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Upload not found"})

    result_user = await db.execute(
        select(UserModel).where(UserModel.id == upload.user_id)
    )
    user = result_user.scalar_one_or_none()

    return {
        "upload_id": str(upload.id),
        "file_name": upload.file_name,
        "file_type": upload.file_type,
        "upload_type": upload.upload_type,
        "status": upload.status,
        "rows_processed": upload.rows_received,
        "rows_valid": upload.rows_valid,
        "uploaded_by": user.email if user else "Unknown",
        "uploaded_at": upload.created_at.isoformat() if upload.created_at else None,
        "parsed_at": upload.parsed_at.isoformat() if upload.parsed_at else None,
    }


@router.delete("/api/files/{upload_id}", status_code=200)
async def delete_upload(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserClaims = Depends(get_current_user),
):
    if not current_user.has_permission(Permission.EDIT_INVESTMENTS):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Insufficient permissions"})

    client_id = current_user.client_id

    result = await db.execute(
        select(SourceFile).where(
            and_(SourceFile.id == upload_id, SourceFile.client_id == client_id)
        )
    )
    upload = result.scalar_one_or_none()

    if not upload:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Upload not found"})

    upload.status = "Deleted"
    await db.commit()

    return {"status": "deleted"}

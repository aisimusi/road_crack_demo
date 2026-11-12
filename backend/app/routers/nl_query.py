from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.text2sql import run_text_query

router = APIRouter(prefix="/api/nl-query", tags=["nl-query"])


@router.post("", response_model=schemas.NLQueryResponse)
def query_by_natural_language(payload: schemas.NLQueryRequest, db: Session = Depends(get_db)) -> schemas.NLQueryResponse:
    try:
        result = run_text_query(db, payload.question)
        db.add(
            models.NLQueryLog(
                question=payload.question,
                generated_sql=result["sql"],
                summary=result["summary"],
                success=True,
                row_count=len(result["data"]),
            )
        )
        db.commit()
        return schemas.NLQueryResponse(**result)
    except (ValueError, PermissionError) as exc:
        db.add(
            models.NLQueryLog(
                question=payload.question,
                generated_sql=None,
                summary=None,
                success=False,
                row_count=0,
                error_message=str(exc),
            )
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        db.add(
            models.NLQueryLog(
                question=payload.question,
                generated_sql=None,
                summary=None,
                success=False,
                row_count=0,
                error_message=str(exc),
            )
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"查询执行失败: {exc}") from exc


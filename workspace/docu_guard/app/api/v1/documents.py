from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import get_db
from app.models.document import Document
from app.schemas.document import DocumentCreate, DocumentOut, DocumentRelease
from app.services.audit_chain import AuditChainService
from app.services.scanner import ScannerService

router = APIRouter()

@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(doc_in: DocumentCreate, db: AsyncSession = Depends(get_db)):
    is_clean, reason = ScannerService.scan_content(doc_in.content)
    doc_status = "clean" if is_clean else "quarantined"
    
    new_doc = Document(
        filename=doc_in.filename,
        content=doc_in.content,
        status=doc_status,
        quarantine_reason=reason
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)
    
    await AuditChainService.log_action(db, "UPLOAD", {
        "document_id": new_doc.id,
        "filename": new_doc.filename,
        "status": new_doc.status
    })
    
    return new_doc

@router.get("", response_model=list[DocumentOut])
async def list_documents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Document))
    return result.scalars().all()

@router.get("/{id}", response_model=DocumentOut)
async def get_document(id: int, db: AsyncSession = Depends(get_db)):
    doc = await db.get(Document, id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc

@router.post("/{id}/release", response_model=DocumentOut)
async def release_document(id: int, release_in: DocumentRelease, db: AsyncSession = Depends(get_db)):
    doc = await db.get(Document, id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if doc.status != "quarantined":
        raise HTTPException(status_code=400, detail="Only quarantined documents can be released")
        
    doc.status = "released"
    doc.reviewer_notes = release_in.reviewer_notes
    doc.released_at = datetime.now(UTC)
    
    await db.commit()
    await db.refresh(doc)
    
    await AuditChainService.log_action(db, "RELEASE", {
        "document_id": doc.id,
        "reviewer_notes": doc.reviewer_notes
    })
    
    return doc

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import current_user, db
from app.models.company import Company
from app.models.user import User
from app.services.storage import upload_file, get_signed_url

router = APIRouter(prefix="/files", tags=["files"])

@router.post("/upload")
async def upload_document(
    company_id: int,
    doc_type: str,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    session: Session = Depends(db)
):
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    if not (getattr(user, "role", "").upper() == "ADMIN" or company.owner_id == user.id):
        raise HTTPException(status_code=403, detail="No autorizado")

    try:
        blob_path = upload_file(file.file, file.filename, user.id, company_id, doc_type)
        url = get_signed_url(blob_path)
        return {"file_path": blob_path, "signed_url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

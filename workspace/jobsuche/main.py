# backend/main.py
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
import uvicorn, uuid, json

app = FastAPI()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# --- Mock KI‑Match (replace with real model) ---
def mock_match(cv_text: str, job_desc: str) -> int:
    # simple keyword overlap → score 0‑100
    cv_set = set(cv_text.lower().split())
    job_set = set(job_desc.lower().split())
    overlap = len(cv_set & job_set)
    return min(100, overlap * 10)

class MatchResult(BaseModel):
    job_id: str
    score: int

@app.post("/match/{job_id}", response_model=MatchResult)
async def match_job(
    job_id: str,
    file: UploadFile = File(...),
    token: str = Depends(oauth2_scheme)
):
    if file.content_type not in ("application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"):
        raise HTTPException(status_code=400, detail="Unsupported file type")
    cv_bytes = await file.read()
    cv_text = cv_bytes.decode(errors="ignore")  # placeholder
    # load job description (mock)
    job_desc = "python django rest api docker kubernetes"
    score = mock_match(cv_text, job_desc)
    return MatchResult(job_id=job_id, score=score)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

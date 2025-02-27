from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import shutil
import os

app = FastAPI()

UPLOAD_DIR = "./uploads"

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# CORS ayarları
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tüm kaynaklardan gelen isteklere izin vermek (daha güvenli bir ayarlama yapılabilir)
    allow_credentials=True,
    allow_methods=["*"],  # Tüm HTTP metodlarına izin vermek
    allow_headers=["*"],  # Tüm HTTP başlıklarına izin vermek
)

@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"filename": file.filename}


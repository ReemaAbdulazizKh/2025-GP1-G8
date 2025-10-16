from fastapi import FastAPI
from shared.firebase_config import db

app = FastAPI()

@app.get("/")
def home():
    return {"message": "Firebase connected successfully ✅"}

# للتأكد أن السيرفر يشتغل
# شغليه بالأمر التالي من التيرمنال:
# uvicorn main:app --reload

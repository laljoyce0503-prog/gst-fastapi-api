import json
import mysql.connector
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware # Import CORS
from pydantic import BaseModel
from typing import Dict, Any, Optional

app = FastAPI()

# --- 1. ENABLE CORS (Crucial for Frontend) ---
# This allows your Vue.js app (usually running on port 3000 or 8080)
# to talk to this Python backend (running on port 8000).
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:8080",
    "http://127.0.0.1:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all origins for development (change for production)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Configuration
db_config = {
    "host": "localhost",
    "user": "root",
    "password": "Joyce@0503", # Updated password as per your request
    "database": "gst_db"
}

# --- Pydantic Models ---
class Submission(BaseModel):
    form_key: str
    form_data: Dict[str, Any]

class SubmissionUpdate(BaseModel):
    form_key: Optional[str] = None
    form_data: Optional[Dict[str, Any]] = None

# --- Helper Functions ---
def get_db_connection():
    return mysql.connector.connect(**db_config)

# --- ROUTES ---

# 0. ROOT ROUTE (Fixes the 404 error on home page)
@app.get("/")
def read_root():
    return {
        "message": "GST API is running!",
        "documentation": "Go to /docs to see the Swagger UI"
    }

# 1. GET ALL
@app.get("/api/submissions")
def get_submissions():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM vueform_sub")
    results = cursor.fetchall()
    conn.close()
    
    for row in results:
        if row["form_data"]:
            row["form_data"] = json.loads(row["form_data"])
            
    return results

# 2. GET ONE
@app.get("/api/submissions/{item_id}")
def get_submission(item_id: int):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM vueform_sub WHERE id = %s", (item_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    if result["form_data"]:
        result["form_data"] = json.loads(result["form_data"])
        
    return result

# 3. POST
@app.post("/api/submissions", status_code=201)
def create_submission(submission: Submission):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    form_data_str = json.dumps(submission.form_data)
    
    sql = "INSERT INTO vueform_sub (form_key, form_data) VALUES (%s, %s)"
    val = (submission.form_key, form_data_str)
    
    cursor.execute(sql, val)
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    
    return {"id": new_id, "message": "Created successfully"}

# 4. PUT
@app.put("/api/submissions/{item_id}")
def update_submission(item_id: int, submission: Submission):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM vueform_sub WHERE id = %s", (item_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Submission not found")

    form_data_str = json.dumps(submission.form_data)
    
    sql = "UPDATE vueform_sub SET form_key = %s, form_data = %s WHERE id = %s"
    val = (submission.form_key, form_data_str, item_id)
    
    cursor.execute(sql, val)
    conn.commit()
    conn.close()
    
    return {"message": "Updated successfully"}

# 5. DELETE
@app.delete("/api/submissions/{item_id}")
def delete_submission(item_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM vueform_sub WHERE id = %s", (item_id,))
    conn.commit()
    
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Submission not found")
        
    conn.close()
    return {"message": "Deleted successfully"}
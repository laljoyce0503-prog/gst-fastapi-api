import json
import mysql.connector
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional, List

app = FastAPI(title="GST Database API")

# --- CORS Configuration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Configuration
#db_config = {"host": "localhost","user": "root","password": "Joyce@0503","database": "gst_db","charset": "utf8mb4"}

import os

db_config = {
    "host": os.getenv("MYSQLHOST"),
    "user": os.getenv("MYSQLUSER"),
    "password": os.getenv("MYSQLPASSWORD"),
    "database": os.getenv("MYSQLDATABASE"),
    "port": int(os.getenv("MYSQLPORT"))
}
# --- Pydantic Models ---
class Submission(BaseModel):
    form_key: str
    form_data: Dict[str, Any]

# --- Helper Functions ---
def get_db_connection():
    try:
        return mysql.connector.connect(**db_config)
    except mysql.connector.Error as err:
        raise HTTPException(status_code=500, detail=f"Database Connection Error: {err}")

def safe_json_loads(data: str):
    """Safely parse JSON from LONGTEXT column, handle plain strings if necessary."""
    try:
        return json.loads(data) if data else {}
    except (json.JSONDecodeError, TypeError):
        return data # Return as raw string if it's not JSON

# --- ROUTES ---

@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "GST API is connected to gst_db",
        "endpoints": {
            "all_data": "/api/submissions",
            "search": "/api/submissions/search?key=your_key",
            "docs": "/docs"
        }
    }

# 1. GET ALL: Fetch existing data from the table
@app.get("/api/submissions", response_model=List[Dict[str, Any]])
def get_submissions():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM vueform_sub ORDER BY id DESC")
        results = cursor.fetchall()
        
        for row in results:
            row["form_data"] = safe_json_loads(row["form_data"])
            
        return results
    finally:
        cursor.close()
        conn.close()

# 2. SEARCH: Filter by form_key (useful if you have many forms)
@app.get("/api/submissions/search")
def search_submissions(key: str = Query(..., description="The form_key to filter by")):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM vueform_sub WHERE form_key = %s", (key,))
        results = cursor.fetchall()
        
        for row in results:
            row["form_data"] = safe_json_loads(row["form_data"])
            
        return results
    finally:
        cursor.close()
        conn.close()

# 3. GET ONE: Retrieve by ID
@app.get("/api/submissions/{item_id}")
def get_submission(item_id: int):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM vueform_sub WHERE id = %s", (item_id,))
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="ID not found in database")
        
        result["form_data"] = safe_json_loads(result["form_data"])
        return result
    finally:
        cursor.close()
        conn.close()

# 4. POST: Add new data
@app.post("/api/submissions", status_code=201)
def create_submission(submission: Submission):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        form_data_str = json.dumps(submission.form_data)
        sql = "INSERT INTO vueform_sub (form_key, form_data) VALUES (%s, %s)"
        cursor.execute(sql, (submission.form_key, form_data_str))
        conn.commit()
        return {"id": cursor.lastrowid, "message": "Record added to database"}
    finally:
        cursor.close()
        conn.close()

# 5. DELETE: Remove a record
@app.delete("/api/submissions/{item_id}")
def delete_submission(item_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM vueform_sub WHERE id = %s", (item_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Record not found")
        return {"message": f"Record {item_id} deleted"}
    finally:
        cursor.close()
        conn.close()

from fastapi import Body

# 4. PATCH: Update partial data inside form_data (e.g., TRN number)
@app.patch("/api/submissions/{item_id}")
def update_submission(item_id: int, payload: Dict[str, Any] = Body(...)):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Fetch existing record
        cursor.execute("SELECT form_data FROM vueform_sub WHERE id = %s", (item_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Record not found")

        # Load existing JSON
        existing_data = safe_json_loads(row["form_data"])
        if not isinstance(existing_data, dict):
            existing_data = {}

        # Merge incoming payload into form_data
        for key, value in payload.items():
            existing_data[key] = value

        # Save back to DB
        cursor.execute(
            "UPDATE vueform_sub SET form_data = %s WHERE id = %s",
            (json.dumps(existing_data), item_id)
        )
        conn.commit()

        return {
            "message": "Record updated successfully",
            "id": item_id,
            "updated_fields": payload
        }

    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
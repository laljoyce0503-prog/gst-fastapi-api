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
@app.get("/api/drafts")
def get_drafts(mobile: Optional[str] = None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, form_data FROM vueform_sub")
    results = cursor.fetchall()
    conn.close()
    
    drafts = []
    for row in results:
        if row["form_data"]:
            try:
                data = json.loads(row["form_data"])
                row_mobile = data.get("_contact_mobile") or data.get("mobile")
                
                # Privacy Filter: If a mobile is provided, only show drafts 
                # that match that mobile number.
                if mobile and str(row_mobile) != str(mobile):
                    continue
                
                # If no mobile is provided, return empty
                if not mobile:
                    continue

                drafts.append({
                    "id": row["id"],
                    "legal_name": data.get("legal_name", "Unknown Name"),
                    "mobile": row_mobile or "N/A"
                })
            except:
                pass
    return drafts

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

# --- New Route: Jurisdiction Proxy ---
import requests

@app.get("/api/jurisdiction/{state_code}/{pincode}")
def get_jurisdiction(state_code: str, pincode: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://reg.gst.gov.in",
        "Referer": "https://reg.gst.gov.in/registration/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin"
    }
    # Disable SSL Warnings for verify=False
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    try:
        results = {}
        # 1. Fetch Commissionerate 
        comm_url = f"https://reg.gst.gov.in/master/jursd/bypincode/commisionerate/{state_code}/{pincode}"
        r1 = requests.get(comm_url, headers=headers, timeout=10, verify=False)
        results["commissionerates"] = r1.json().get("data", []) if r1.status_code == 200 else []
        
        # 2. Fetch Ward
        ward_url = f"https://reg.gst.gov.in/master/jursd/bypincode/ward/{state_code}/{pincode}"
        r2 = requests.get(ward_url, headers=headers, timeout=10, verify=False)
        results["wards"] = r2.json().get("data", []) if r2.status_code == 200 else []

        # 3. Fetch Division
        div_url = f"https://reg.gst.gov.in/master/jursd/bypincode/division/{state_code}/WT/{pincode}"
        r3 = requests.get(div_url, headers=headers, timeout=10, verify=False)
        results["divisions"] = r3.json().get("data", []) if r3.status_code == 200 else []
        
        # 4. Fetch Range
        results["ranges"] = []
        if results["divisions"] and len(results["divisions"]) > 0:
            div_code = results["divisions"][0].get("c")
            range_url = f"https://reg.gst.gov.in/master/jursd/bypincode/range/{state_code}/{div_code}/{pincode}"
            r4 = requests.get(range_url, headers=headers, timeout=10, verify=False)
            results["ranges"] = r4.json().get("data", []) if r4.status_code == 200 else []
            
        return results
    except Exception as e:
        return {
            "commissionerates": [],
            "wards": [],
            "divisions": [],
            "ranges": [],
            "error": str(e)
        }

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

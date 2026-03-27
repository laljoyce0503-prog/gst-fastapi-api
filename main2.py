import json
import mysql.connector
import requests
from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import os

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

db_config = {"host": os.getenv("MYSQLHOST"),"user": os.getenv("MYSQLUSER"),"password": os.getenv("MYSQLPASSWORD"),"database": os.getenv("MYSQLDATABASE"),"port": int(os.getenv("MYSQLPORT"))}
# --- Pydantic Models ---
class Submission(BaseModel):
    form_key: str
    form_data: Dict[str, Any]

class Draft(BaseModel):
    mobile_number: str
    form_data: Dict[str, Any]
    current_page: int
    status: Optional[str] = "draft"

# --- Helper Functions ---
def get_db_connection():
    try:
        return mysql.connector.connect(**db_config)
    except mysql.connector.Error as err:
        raise HTTPException(status_code=500, detail=f"Database Connection Error: {err}")

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Create drafts table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vueform_drafts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                mobile_number VARCHAR(20) NOT NULL,
                form_data LONGTEXT NOT NULL,
                current_page INT DEFAULT 0,
                status VARCHAR(20) DEFAULT 'draft',
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX (mobile_number)
            )
        """)
        conn.commit()
    finally:
        cursor.close()
        conn.close()

# Initialize DB on startup
init_db()

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
            "drafts": "/api/drafts",
            "docs": "/docs"
        }
    }

# --- DRAFT ROUTES ---

@app.post("/api/drafts", status_code=201)
def save_draft(draft: Draft):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # We always upsert for a specific mobile number or if you want multiple drafts, we can handle by ID
        # For simplicity based on requirements, we check if draft exists for this mobile
        form_data_str = json.dumps(draft.form_data)
        
        # Check if a draft already exists for this mobile number to update it, 
        # or we could just allow multiple drafts. Requirement says "Show list of saved drafts".
        # So we allow multiple drafts.
        sql = """
            INSERT INTO vueform_drafts (mobile_number, form_data, current_page, status) 
            VALUES (%s, %s, %s, %s)
        """
        cursor.execute(sql, (draft.mobile_number, form_data_str, draft.current_page, draft.status))
        conn.commit()
        return {"id": cursor.lastrowid, "message": "Draft saved successfully"}
    finally:
        cursor.close()
        conn.close()

@app.put("/api/drafts/{draft_id}")
def update_draft(draft_id: int, draft: Draft):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        form_data_str = json.dumps(draft.form_data)
        sql = """
            UPDATE vueform_drafts 
            SET form_data = %s, current_page = %s, status = %s 
            WHERE id = %s
        """
        cursor.execute(sql, (form_data_str, draft.current_page, draft.status, draft_id))
        conn.commit()
        return {"message": "Draft updated successfully"}
    finally:
        cursor.close()
        conn.close()

@app.get("/api/drafts/{mobile_or_id}")
def get_drafts_by_mobile_or_id(mobile_or_id: str):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Check if it's an ID (numeric and not 10 digits)
        is_id = mobile_or_id.isdigit() and len(mobile_or_id) < 10
        
        if is_id:
            cursor.execute("SELECT * FROM vueform_drafts WHERE id = %s", (mobile_or_id,))
            results = cursor.fetchall()
        else:
            # Search by dedicated column AND inside JSON for _contact_mobile
            sql = "SELECT * FROM vueform_drafts WHERE mobile_number = %s OR form_data LIKE %s ORDER BY last_updated DESC"
            cursor.execute(sql, (mobile_or_id, f'%"{mobile_or_id}"%',))
            results = cursor.fetchall()
            
        final_results = []
        for row in results:
            row["form_data"] = safe_json_loads(row["form_data"])
            
            if is_id:
                final_results.append(row)
                continue

            # Verification logic for JSON content (Mobile or Email)
            def is_match(data):
                if isinstance(data, dict):
                    # Check mobile
                    if str(data.get("_contact_mobile", "")) == mobile_or_id: return True
                    if str(data.get("mobile", "")) == mobile_or_id: return True
                    # Check email
                    if str(data.get("_contact_email", "")).lower() == mobile_or_id.lower(): return True
                    if str(data.get("email", "")).lower() == mobile_or_id.lower(): return True
                    
                    return any(is_match(v) for v in data.values())
                elif isinstance(data, list):
                    return any(is_match(i) for i in data)
                return False
            
            if row.get("mobile_number") == mobile_or_id or is_match(row["form_data"]):
                final_results.append(row)

        return final_results
    finally:
        cursor.close()
        conn.close()

@app.get("/api/submissions/search/mobile/{mobile_or_id}")
def search_submissions_by_mobile_or_id(mobile_or_id: str):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        is_id = mobile_or_id.isdigit() and len(mobile_or_id) < 10
        
        if is_id:
            cursor.execute("SELECT * FROM vueform_sub WHERE id = %s", (mobile_or_id,))
            results = cursor.fetchall()
        else:
            # Search inside JSON form_data for _contact_mobile
            sql = "SELECT * FROM vueform_sub WHERE form_data LIKE %s ORDER BY id DESC"
            cursor.execute(sql, (f'%"{mobile_or_id}"%',))
            results = cursor.fetchall()
        
        final_results = []
        for row in results:
            row["form_data"] = safe_json_loads(row["form_data"])
            
            if is_id:
                final_results.append(row)
                continue

            # Verification logic for JSON content (Mobile or Email)
            def is_match(data):
                if isinstance(data, dict):
                    # Check mobile
                    if str(data.get("_contact_mobile", "")) == mobile_or_id: return True
                    if str(data.get("mobile", "")) == mobile_or_id: return True
                    # Check email
                    if str(data.get("_contact_email", "")).lower() == mobile_or_id.lower(): return True
                    if str(data.get("email", "")).lower() == mobile_or_id.lower(): return True
                    
                    return any(is_match(v) for v in data.values())
                elif isinstance(data, list):
                    return any(is_match(i) for i in data)
                return False
            
            if is_match(row["form_data"]):
                final_results.append(row)
                
        return final_results
    finally:
        cursor.close()
        conn.close()

@app.get("/api/drafts/id/{draft_id}")
def get_draft_by_id(draft_id: int):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM vueform_drafts WHERE id = %s", (draft_id,))
        result = cursor.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Draft not found")
        result["form_data"] = safe_json_loads(result["form_data"])
        return result
    finally:
        cursor.close()
        conn.close()

@app.delete("/api/drafts/{draft_id}")
def delete_draft(draft_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM vueform_drafts WHERE id = %s", (draft_id,))
        conn.commit()
        return {"message": "Draft deleted"}
    finally:
        cursor.close()
        conn.close()

# --- SUBMISSION ROUTES ---

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

# 4. POST: Add new submission
@app.post("/api/submissions", status_code=201)
def create_submission(submission: Submission):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 🔥 THE UNWRAPPER: If frontend sends {form_data: {form_data: ...}}, we stay flat.
        data = submission.form_data
        while "form_data" in data and isinstance(data["form_data"], dict):
            data = data["form_data"]

        form_data_str = json.dumps(data)
        sql = "INSERT INTO vueform_sub (form_key, form_data) VALUES (%s, %s)"
        cursor.execute(sql, (submission.form_key, form_data_str))
        conn.commit()
        return {"id": cursor.lastrowid, "message": "Record added successfully"}
    finally:
        cursor.close()
        conn.close()

import requests

@app.get("/api/proxy/jurisdiction/{path:path}")
def proxy_jurisdiction(path: str):
    """
    Generic proxy for GST Jurisdiction APIs (Commissionerate, Division, Range).
    """
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://reg.gst.gov.in",
        "Referer": "https://reg.gst.gov.in/registration/"
    }

    url = f"https://reg.gst.gov.in/master/jursd/bypincode/{path}"

    try:
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        if response.status_code == 200:
            return response.json()
        return {"data": [], "error": f"Upstream returned {response.status_code}"}
    except Exception as e:
        print(f"Proxy error for path {path}: {e}")
        return {"data": [], "error": str(e)}


@app.get("/api/ghataks/{state_code}")
def get_ghataks(state_code: str):
    """
    Fetch Sector/Circle/Ward (Ghatak) from GST portal
    """
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://reg.gst.gov.in",
        "Referer": "https://reg.gst.gov.in/registration/"
    }

    url = f"https://reg.gst.gov.in/master/jursd/cd/state/{state_code}"

    try:
        response = requests.get(url, headers=headers, timeout=10, verify=False)

        if response.status_code == 200:
            data = response.json()

            # ✅ SAFE PARSING
            if (
                isinstance(data, dict)
                and "data" in data
                and isinstance(data["data"], list)
                and len(data["data"]) > 0
            ):
                first = data["data"][0]

                if isinstance(first, dict) and "n" in first:
                    return first["n"]

        return []
    except Exception as e:
        print(f"Error fetching ghataks for state {state_code}: {e}")
        return []        

# 5. PUT: Full replacement of existing submission
@app.put("/api/submissions/{item_id}")
def update_submission_put(item_id: int, submission: Submission):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM vueform_sub WHERE id = %s", (item_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Record not found")

        # 🔥 THE UNWRAPPER: Same logic for updates
        data = submission.form_data
        while "form_data" in data and isinstance(data["form_data"], dict):
            data = data["form_data"]

        form_data_str = json.dumps(data)
        sql = "UPDATE vueform_sub SET form_key = %s, form_data = %s WHERE id = %s"
        cursor.execute(sql, (submission.form_key, form_data_str, item_id))
        conn.commit()
        return {"message": "Updated successfully", "id": item_id}
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


@app.get("/api/gst/districts/{gst_code}")
def get_gst_districts(gst_code: str):
    url = f"https://reg.gst.gov.in/master/jursd/get/districts/{gst_code}"

    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://reg.gst.gov.in/"},
            timeout=10
        )

        if response.status_code != 200:
            # PROFESSIONAL FIX: Silence the error and return empty list to prevent frontend 500 crash.
            # This allows the frontend fallback to trigger without a 'Red Error'.
            return []

        data = response.json()
        if not data or "data" not in data:
            return []

        return [
            {"value": d.get("c") or d.get("v") or "", "label": d.get("n") or d.get("l") or ""}
            for d in data["data"]
        ]

    except Exception as e:
        # PROFESSIONAL FIX: Silent catch - never return 500 for a proxy lookup
        print(f"District lookup failed: {str(e)}")
        return []
# 7. PATCH: Update partial data inside form_data (merge)
@app.patch("/api/submissions/{item_id}")
def patch_submission(item_id: int, payload: Dict[str, Any] = Body(...)):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT form_data FROM vueform_sub WHERE id = %s", (item_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Record not found")

        existing_data = safe_json_loads(row["form_data"])
        if not isinstance(existing_data, dict):
            existing_data = {}

        for key, value in payload.items():
            existing_data[key] = value

        cursor.execute(
            "UPDATE vueform_sub SET form_data = %s WHERE id = %s",
            (json.dumps(existing_data), item_id)
        )
        conn.commit()

        return {"message": "Patched successfully", "id": item_id, "updated_fields": list(payload.keys())}
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main2:app", host="0.0.0.0", port=8000, reload=True)

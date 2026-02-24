import json
import requests
import sys
import traceback
import os
import time
from datetime import datetime
from imapclient import IMAPClient, SEEN
import pyzmail
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys

# ================= CONFIGURATION =================
API_BASE_URL = "http://127.0.0.1:8000/api/submissions"
SUBMISSION_ID = 50

# Fallback/Initial Configuration
TRN_NUMBER_GLOBAL = "242500319304TRN" 
EMAIL_ID = "laljoyce0503@gmail.com"
APP_PASSWORD = "lcpodhgqolihjvpa"
SENDER_EMAIL = "donotreply@gst.gov.in"
IMAP_SERVER = "imap.gmail.com"
UPLOAD_DIR = r"C:\Users\YourUser\Documents\GST_Uploads" # Ensure this path is correct on your machine

# ================= API HELPERS =================
def fetch_data_from_api(submission_id):
    """
    Fetches submission details from the API instead of MySQL.
    """
    urls_to_try = [f"{API_BASE_URL}/{submission_id}", f"{API_BASE_URL}/{submission_id}/"]
    
    last_error = None
    for url in urls_to_try:
        try:
            print(f"🔍 Fetching data from API: {url}...")
            response = requests.get(url)
            if response.status_code == 200:
                api_response = response.json()
                
                # 1. Extract TRN Number
                trn_number = api_response.get("trn_number")

                # 2. Extract Form Data
                raw_form_data = api_response.get("form_data")
                
                if raw_form_data is None:
                    data = api_response
                elif isinstance(raw_form_data, str):
                    try:
                        data = json.loads(raw_form_data)
                    except json.JSONDecodeError:
                        data = raw_form_data 
                else:
                    data = raw_form_data

                return data, trn_number
            else:
                last_error = f"Status {response.status_code}"
        except Exception as e:
            last_error = str(e)
            
    print(f"❌ API Request Failed for ID {submission_id}. Last error: {last_error}")
    sys.exit(1)

def save_trn_to_api(submission_id, trn_number):
    """
    Updates the TRN number in the API.
    Strategy: GET current state -> Modify field -> PUT full object back.
    """
    print(f"[API] Starting TRN update process for ID {submission_id}...")
    
    urls_to_try = [f"{API_BASE_URL}/{submission_id}", f"{API_BASE_URL}/{submission_id}/"]
    working_url = None
    current_payload = None

    for url in urls_to_try:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                working_url = url
                current_payload = response.json()
                print(f"   ✅ Fetched current data from {url}")
                break
        except Exception as e:
            pass

    if not working_url or not current_payload:
        print("❌ Could not fetch entry to update. API update failed.")
        return

    # Modify the payload
    print(f"   [MODIFY] Setting trn_number to {trn_number}")
    current_payload['trn_number'] = trn_number

    # Send back the updated payload
    methods = [requests.put, requests.patch, requests.post]
    
    for method in methods:
        method_name = method.__name__.upper()
        try:
            response = method(working_url, json=current_payload, timeout=10)
            
            if response.status_code in [200, 201, 202, 204]:
                print(f"✅ API Updated Successfully using {method_name}!")
                return
            else:
                print(f"   ⚠️ {method_name} failed: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"   ⚠️ {method_name} exception: {e}")

    print("❌ Failed to update TRN in API after all attempts. Continuing with local memory only...")

# ================= SELENIUM HELPERS =================
def safe_input(driver, element_id, value):
    if value is None: return
    try:
        element = driver.find_element(By.ID, element_id)
        driver.execute_script("""
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
            arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
            arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));
        """, element, str(value))
    except Exception as e:
        print(f"⚠️ Could not fill field {element_id}: {e}")

def format_date_for_ui(date_str):
    if not date_str: return ""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        try:
            datetime.strptime(date_str, "%d/%m/%Y")
            return date_str
        except ValueError:
            return date_str

def set_input(driver, element, value):
    driver.execute_script("""
        arguments[0].value = arguments[1];
        arguments[0].dispatchEvent(new Event('input',{bubbles:true}));
        arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
        arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
    """, element, value)

def angular_select_by_value(driver, element_id, value):
    if not value:
        return
    try:
        wait = WebDriverWait(driver, 10)
        select_elem = wait.until(EC.presence_of_element_located((By.ID, element_id)))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", select_elem)
        select = Select(select_elem)
        select.select_by_value(value)
        driver.execute_script("""
            arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
            arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));
        """, select_elem)
        print(f"✅ Selected '{value}' for #{element_id}")
    except Exception as e:
        print(f"❌ Failed to select '{value}' for #{element_id}: {e}")

def set_date_picker(driver, element_id, date_val):
    if not date_val: return
    try:
        wait = WebDriverWait(driver, 10)
        elem = wait.until(EC.presence_of_element_located((By.ID, element_id)))
        driver.execute_script("""
            arguments[0].removeAttribute('readonly');
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('input', {bubbles:true}));
            arguments[0].dispatchEvent(new Event('change', {bubbles:true}));
            arguments[0].dispatchEvent(new Event('blur', {bubbles:true}));
        """, elem, date_val)
        print(f"✅ Set date '{date_val}' for #{element_id}")
    except Exception as e:
        print(f"❌ Failed to set date for #{element_id}: {e}")

def stop_on_error(driver, message):
    print("\n" + "!"*30)
    print(f" ERROR: {message}")
    print("!"*30)
    sys.exit(1)

def angular_set_value(driver, element, value):
    driver.execute_script("""
        arguments[0].value = arguments[1];
        arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
        arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
        arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));
        arguments[0].dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    """, element, value)

def hide_address_map(driver):
    driver.execute_script("""
        let map = document.getElementById('map1');
        if (map) { map.style.display = 'none'; }
        let map2 = document.getElementById('map2');
        if (map2) { map2.style.display = 'none'; }
    """)

# ================= DATA PARSER =================
def parse_dummy15_data(data):
    """Map API JSON to script variables"""
    parsed = {
        # ================= BUSINESS DETAILS =================
        "legal_name": data.get("legal_name") or "",
        "pan": data.get("pan") or "",
        "pan_date": data.get("pan_date") or "",
        "constitution": data.get("Constitution of Business") or "",
        "trade_name": data.get("trade_name") or "",
        "state": data.get("state") or "",
        "district_fixed": data.get("district_fixed") or data.get("District") or "", # Added fallback for "District" key
        "toggle": data.get("toggle", False),
        "toggle_1": data.get("toggle_1", False),
        "radioBlocks": data.get("radioBlocks", 0),
        "text": data.get("text"),
        "reason": data.get("reason") or data.get("Reason to obtain registration") or "CRTH",
        "commencement_date": format_date_for_ui(data.get("commencement_date") or data.get("commencement_date_1")),
        "existing_registrations": data.get("existing_registrations_list", []),
        "file_name": data.get("file"),

        # ================= PROMOTER DETAILS =================
        "name_first": data.get("name_first") or "",
        "name_middle": data.get("name_middle") or "",
        "name_last": data.get("name_last") or "",
        "father_first": data.get("father_first") or "",
        "father_middle": data.get("father_middle") or "",
        "father_last": data.get("father_last") or "",
        "dob": format_date_for_ui(data.get("dob")),
        "mobile": data.get("mobile") or "",
        "email": data.get("email") or "",
        "telephone": data.get("telephone") or "",
        "radiogroup": data.get("radiogroup") or "",
        "designation": data.get("designation") or "Director",
        "din": data.get("din") or "",
        "toggle_2": data.get("toggle_2", False),
        "pan_proprietor": data.get("pan_proprietor") or data.get("pan"),
        "passport": data.get("passport"),
        "aadhaar": data.get("aadhaar"),
        "country": data.get("country") or "IND",

        # ================= RESIDENTIAL ADDRESS =================
        "pin_code": data.get("pin_code") or "",
        "state_res": data.get("state_res") or "",
        "district_res": data.get("district_res") or "",
        "city_res": data.get("city_res") or "",
        "locality": data.get("locality") or "",
        "road_street_res": data.get("road_street_res") or "",
        "premises_name": data.get("premises_name") or "",
        "building_no_res": data.get("building_no_res") or "",
        "floor_no_res": data.get("floor_no_res") or "",
        "landmark_res": data.get("landmark_res") or "",
        "photo": data.get("photo"),
        "Also Authorized Signatory": data.get("Also Authorized Signatory", False),
        "is_primary": data.get("is_primary", False),

        # ================= AUTHORIZED SIGNATORY =================
        "as_name_first": data.get("as_name_first") or "",
        "as_name_middle": data.get("as_name_middle") or "",
        "as_name_last": data.get("as_name_last") or "",
        "as_father_first": data.get("as_father_first") or "",
        "as_father_middle": data.get("as_father_middle") or "",
        "as_father_last": data.get("as_father_last") or "",
        "as_dob": data.get("as_dob") or "",
        "as_mobile": data.get("as_mobile") or "",
        "as_email": data.get("as_email") or "",
        "as_telephone": data.get("as_telephone"),
        "radiogroup_1": data.get("radiogroup_1"),
        "as_designation": data.get("as_designation") or "",
        "as_din": data.get("as_din") or "",
        "as_pan": data.get("as_pan") or "",
        "toggle_3": data.get("toggle_3", False),
        "as_passport": data.get("as_passport"),
        "as_aadhaar": data.get("as_aadhaar"),
        "as_country": data.get("as_country") or "IND",
        "as_pin": data.get("as_pin") or "",
        "as_state": data.get("as_state"),
        "as_district": data.get("as_district"),
        "as_city": data.get("as_city"),
        "as_locality": data.get("as_locality") or "",
        "as_road": data.get("as_road") or "",
        "as_premises": data.get("as_premises") or "",
        "as_bno": data.get("as_bno") or "",
        "as_floor": data.get("as_floor") or "",
        "as_landmark": data.get("as_landmark") or "",
        "as_proof_type": data.get("as_proof_type") or "",
        "as_proof_file": data.get("as_proof_file"),
        "as_photo": data.get("as_photo"),

        # ================= REPRESENTATIVE =================
        "toggle_4": data.get("toggle_4",False) ,
        "radiogroup_2": data.get("radiogroup_2"),
        "enrolment_id": data.get("enrolment_id") or "",
        "rep_name_first": data.get("rep_name_first") or "",
        "rep_name_middle": data.get("rep_name_middle") or "",
        "rep_name_last": data.get("rep_name_last") or "",
        "rep_designation": data.get("rep_designation") or "",
        "rep_mobile": data.get("rep_mobile") or "",
        "rep_email": data.get("rep_email") or "",
        "rep_pan": data.get("rep_pan") or "",
        "rep_aadhaar": data.get("rep_aadhaar"),
        "rep_telephone": data.get("rep_telephone"),
        "rep_fax": data.get("rep_fax"),

        # ================= PRINCIPAL PLACE OF BUSINESS =================
        "ppb_pin": data.get("ppb_pin") or "",
        "ppb_state": data.get("ppb_state") or "",
        "ppb_district": data.get("ppb_district") or "",
        "ppb_city": data.get("ppb_city"),
        "ppb_locality": data.get("ppb_locality") or "",
        "ppb_road": data.get("ppb_road") or "",
        "ppb_premises": data.get("ppb_premises") or "",
        "ppb_bno": data.get("ppb_bno") or "",
        "ppb_floor": data.get("ppb_floor") or "",
        "ppb_landmark": data.get("ppb_landmark") or "",
        "ppb_lat": data.get("ppb_lat"),
        "ppb_long": data.get("ppb_long"),
        "ppb_email": data.get("ppb_email"),
        "ppb_office_tel": data.get("ppb_office_tel"),
        "ppb_mobile": data.get("ppb_mobile"),
        "ppb_fax": data.get("ppb_fax"),
        "ppb_possession_type": data.get("ppb_possession_type") or "OWN",
        "ppb_proof_doc": data.get("ppb_proof_doc") or "ELCB",
        "ppb_file": data.get("ppb_file"),
        "center_division":data.get("center_division"),
        "center_range":data.get("center_range"),
        "apb_count":data.get("apb_count"),
        "apb_pin":data.get("apb_pin"),
        "apb_state":data.get("apb_state"),
        "apb_district":data.get("apb_district"),
        "apb_city":data.get("apb_city"),
        "apb_locality":data.get("apb_locality"),
        "apb_road":data.get( "apb_road"),
        "apb_premises":data.get("apb_premises"),
        "apb_bno":data.get("apb_bno"),
        "apb_floor":data.get("apb_floor"),
        "apb_landmark":data.get("apb_landmark"),
        "apb_email":data.get("apb_email"),
        "apb_mobile":data.get("apb_mobile"),
        "apb_possession_type":data.get("apb_possession_type"),
        "apb_proof_doc":data.get("apb_proof_doc"),
        "apb_bonded_warehouse":data.get("apb_bonded_warehouse"),
        "apb_eou":data.get("apb_eou"),
        "apb_export":data.get("apb_export"),
        "apb_factory":data.get("apb_factory"),
        "apb_import":data.get("apb_import"),
        "apb_services":data.get("apb_services"),
        "apb_leasing":data.get("apb_leasing"),
        "apb_office":data.get("apb_office"),
        "apb_recipient":data.get("apb_recipient"),
        "apb_retail":data.get("apb_retail"),
        "apb_warehouse":data.get("apb_warehouse"),
        "apb_wholesale":data.get("apb_wholesale"),
        "apb_works_contract":data.get("apb_works_contract"),
        "apb_others":data.get("apb_others"),
        
        # ================= GOODS / SERVICES =================
        "hsn_search": data.get("hsn_search"),
        "commodities_list": data.get("commodities_list", []),
        "sac_search": data.get("sac_search"),
        "services_list": data.get("services_list", []),
        
        #================== STATE SPECIFIC INFO ================
        "electricity_board":data.get("electricity_board"),
        "consumer_number":data.get("consumer_number"),
        "prof_tax_ec": data.get( "prof_tax_ec"),
        "prof_tax_rc":data.get("prof_tax_rc"),
        "state_excise_lic": data.get("state_excise_lic"),
        "excise_person_name": data.get("excise_person_name"),
        
        # ================= VERIFICATION =================
        "opt_for_aadhaar": data.get("opt_for_aadhaar", True),
        "declaration": data.get("declaration", False),
        "signatory": data.get("signatory"),
        "place": data.get("place") or "BENGALURU",
        "designation_ver": data.get("designation_ver"),
        "date_ver": data.get("date_ver"),
        "district": data.get("district"),
        "Reason to obtain registration": data.get("Reason to obtain registration")
    }
    return parsed

# ================= MAIN EXECUTION =================
if __name__ == "__main__":
    
    # 0. Fetch Data from API First
    print("\n" + "="*50)
    print(f" FETCHING DATA FOR ID: {SUBMISSION_ID} FROM API")
    print("="*50)
    
    raw_api_data, api_trn_number = fetch_data_from_api(SUBMISSION_ID)
    final_data = parse_dummy15_data(raw_api_data)
    print("✅ API Data Fetched and Parsed Successfully")

    # Initialize Driver
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    # options.add_argument("--headless") # Uncomment if you don't want to see browser
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 30)
    
    NEW_TRN_NUMBER = None

    try:
        # ==============================================================================
        # PART 1: NEW REGISTRATION (Run if TRN is NOT present)
        # ==============================================================================
        
        # NOTE: logic here checks if we already have a TRN from API or Config.
        # If we do not have a TRN, we generate one.
        
        # If API provided a TRN, use it. Otherwise, generate new.
        if api_trn_number:
            print(f"ℹ️ TRN found in API data: {api_trn_number}. Skipping Part 1 (Generation).")
            NEW_TRN_NUMBER = api_trn_number
        else:
            print("\n" + "="*50)
            print(" PART 1: STARTING NEW REGISTRATION (Generating TRN)")
            print("="*50)

            # Navigate to GST Registration Page
            print("Navigating to GST Portal...")
            driver.get("https://reg.gst.gov.in/registration/")
            time.sleep(2)

            print(f"Starting New Registration Form Filling for {final_data['legal_name']}...")

            # 1. SELECT "I AM A" (Application Type)
            appln_type_elem = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "applnType")))
            select_type = Select(appln_type_elem)
            select_type.select_by_value("APLRG")    # Taxpayer
            print(" Selected: Taxpayer")

            # 2. SELECT STATE / UT - DYNAMIC
            state_elem = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "applnState")))
            select_state = Select(state_elem)
            try:
                # Try selecting by text first (e.g. "Gujarat")
                select_state.select_by_visible_text(final_data["state"])
                print(f" Selected State: {final_data['state']}")
            except Exception as e:
                print(f"⚠️ Could not select state by text '{final_data['state']}', using fallback '24'. Error: {e}")
                select_state.select_by_value("24") # Fallback to Gujarat ID
            time.sleep(1.5) 

            # 3. SELECT DISTRICT - DYNAMIC
            dist_elem = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "applnDistr")))
            select_dist = Select(dist_elem)
            try:
                # Try selecting by value (e.g. "GJAHM")
                select_dist.select_by_value(final_data["district_fixed"])
                print(f" Selected District: {final_data['district_fixed']}")
            except Exception as e:
                print(f"⚠️ Could not select district '{final_data['district_fixed']}', using fallback 'GJAHM'. Error: {e}")
                select_dist.select_by_value("GJAHM")   # Fallback
            

            # 4. ENTER LEGAL NAME - DYNAMIC
            legal_name_input = driver.find_element(By.ID, "bnm")
            legal_name_input.clear()
            legal_name_input.send_keys(final_data["legal_name"])
            print(f" Entered Legal Name: {final_data['legal_name']}")

            # 5. ENTER PAN - DYNAMIC
            pan_input = driver.find_element(By.ID, "pan_card")
            pan_input.clear()
            pan_input.send_keys(final_data["pan"]) 
            print(f" Entered PAN: {final_data['pan']}")

            # 6. ENTER EMAIL - DYNAMIC
            email_input = driver.find_element(By.ID, "email")
            email_input.clear()
            email_input.send_keys(final_data["email"])
            print(f" Entered Email: {final_data['email']}")

            # 7. ENTER MOBILE - DYNAMIC
            mobile_input = driver.find_element(By.ID, "mobile")
            mobile_input.clear()
            mobile_input.send_keys(final_data["mobile"])
            print(f" Entered Mobile: {final_data['mobile']}")

            # 8. CAPTCHA & FIRST PROCEED
            print("\n-------------------------------------------------------------")
            print(" PLEASE SOLVE CAPTCHA MANUALLY IN BROWSER")
            print(" Waiting 25 seconds...")
            print("-------------------------------------------------------------")

            time.sleep(25)

            first_proceed = WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']")))
            first_proceed.click()
            print(" First Proceed clicked (CAPTCHA page)")

            # 9. EXISTING REGISTRATION TABLE PAGE
            print(" Waiting for Existing Registration table...")
            try:
                table_proceed = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(
                        (By.XPATH, "//a[contains(@class,'btn-primary') and contains(text(),'Proceed')]")))
                table_proceed.click()
                print(" Proceed clicked on Existing Registration page")
            except:
                print(" Existing registration table might not have appeared, continuing...")

            # 10. OTP PAGE (Mobile + Email)
            print(" Waiting for OTP input fields...")
            print(" Waiting for user input...")
            input("👉 ACTION REQUIRED: Check Email/Mobile for OTP, enter in browser, then Press ENTER here...")
            
            otp_proceed = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and contains(text(),'Proceed')]")))
            otp_proceed.click()
            print(" OTP Proceed clicked")

            # 11. WAIT FOR TRN & EXTRACT IT
            print(" Waiting for TRN generation page...")

            WebDriverWait(driver, 90).until(
                EC.text_to_be_present_in_element((By.XPATH, "//span[@data-ng-bind='trn']"),"TRN"))

            trn_span = driver.find_element(By.XPATH, "//span[@data-ng-bind='trn']")
            NEW_TRN_NUMBER = trn_span.text.strip()

            if not NEW_TRN_NUMBER or "TRN" not in NEW_TRN_NUMBER:
                stop_on_error(driver, "TRN not found after text binding")

            print(f"✅ TRN GENERATED: {NEW_TRN_NUMBER}")
            
            # Save TRN to API
            save_trn_to_api(SUBMISSION_ID, NEW_TRN_NUMBER)

        # ==============================================================================
        # PART 2: FILLING DETAILS USING TRN
        # ==============================================================================
        print("\n" + "="*50)
        print(" PART 2: CONTINUING WITH TRN LOGIN & FORM FILLING")
        print("="*50)

        trn_to_use = NEW_TRN_NUMBER if NEW_TRN_NUMBER else api_trn_number
        
        if not trn_to_use:
            stop_on_error(driver, "No TRN available (Neither from API nor generated). Exiting.")

        # 2. NAVIGATE TO PORTAL
        driver.get("https://reg.gst.gov.in/registration/")
        
        # Click TRN Radio
        trn_label = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//label[contains(.,'Temporary Reference Number')]")
        ))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", trn_label)

        # 3. TRN LOGIN & CAPTCHA
        trn_input = wait.until(EC.presence_of_element_located((By.ID, "trnno")))
        trn_input.clear()
        trn_input.send_keys(trn_to_use)
        print(f"✅ TRN entered: {trn_to_use}")

        print("\n⏳ ACTION REQUIRED: Enter CAPTCHA in the browser window.")
        print("Wait 15 seconds for manual entry...")
        time.sleep(15) 

        # Attempt to click Proceed after Captcha
        driver.execute_script("""
            const btns = Array.from(document.querySelectorAll("button"));
            const proceedBtn = btns.find(b => b.textContent.trim().toUpperCase() === "PROCEED");
            if (proceedBtn) proceedBtn.click();
        """)
        print("👆 Proceed (Post-Captcha) clicked.")

        # 4. OTP LOGIN
        print("\n⏳ ACTION REQUIRED: Enter OTP in the browser window.")
        input("👉 Once OTP is typed, press ENTER here in the terminal to trigger the final Proceed...")

        driver.execute_script("""
            const btns = Array.from(document.querySelectorAll("button"));
            const proceedBtn = btns.find(b => b.textContent.trim().toUpperCase() === "PROCEED" && !b.disabled);
            if (proceedBtn) proceedBtn.click();
        """)
        print("✅ OTP Proceed clicked.")

        # Wait until Dashboard loads
        wait.until(lambda d: "dashboard" in d.current_url.lower())
        print("✅ Dashboard loaded")
        time.sleep(2)

        # 5. NAVIGATE TO EDIT
        try:
            edit_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH,"//button[.//i[contains(@class,'fa-pencil')]]")
            ))
            driver.execute_script("arguments[0].click();", edit_btn)
            print("✅ Edit Application clicked")
        except:
             print("⚠️ Could not find Edit pencil icon. Checking if already in form...")

        time.sleep(3)
        # Wait for Business Details
        wait.until(EC.visibility_of_element_located((By.ID, "tnm")))

        # 6. AUTOFILL BUSINESS DETAILS
        print("⏳ Filling Business Details...")
        # 6. AUTOFILL BUSINESS DETAILS
        # Trade Name
        tnm = wait.until(EC.presence_of_element_located((By.ID, "tnm")))
        set_input(driver, tnm, final_data["trade_name"])
        time.sleep(1)
        # Constitution & District
        angular_select_by_value(driver, "bd_ConstBuss", final_data["constitution"])
        angular_select_by_value(driver, "dst", final_data["district_fixed"]) # Use district_fixed from Part 1 / Data
        time.sleep(2)

        # C.1 Option for registration under Rule 14A -> Select YES
        try:
            rule14a_yes = wait.until(EC.presence_of_element_located((By.ID, "bd_yes")))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", rule14a_yes)
            print("✅ Selected YES for Rule 14A")
        except Exception as e:
            print(f"❌ Failed to select Rule 14A: {e}")

        # Reason & Dates
        angular_select_by_value(driver, "bd_rsl", final_data["reason"])
        set_date_picker(driver, "bd_cmbz", final_data["commencement_date"])
        set_date_picker(driver, "lib", final_data["commencement_date"])

        # Existing Registrations
        for reg in final_data["existing_registrations"]:
            if reg.get("reg_no"):
                angular_select_by_value(driver, "exty", reg.get("type"))
                set_input(driver, wait.until(EC.presence_of_element_located((By.ID, "exno"))), reg.get("reg_no"))
                set_date_picker(driver, "exdt", format_date_for_ui(reg.get("date")))
                driver.execute_script("document.getElementsByName('addexist')[0].click();")
                time.sleep(1)

        # 7. DOCUMENT UPLOAD
        if final_data["file_name"]:
            try:
                full_file_path = os.path.join(UPLOAD_DIR, final_data["file_name"]).replace("/", "\\")
                if os.path.exists(full_file_path):
                    upload_input = driver.find_element(By.ID, "tr_upload")
                    upload_input.send_keys(full_file_path)
                    print(f"✅ Document uploaded: {full_file_path}")
                    time.sleep(3) 
                else:
                    print(f"⚠️ Warning: File not found at {full_file_path}")
            except Exception as e:
                print(f"❌ Document upload failed: {e}")
        
        # 8. SAVE & CONTINUE (Fix for Intercepted Click)
        try:
            print("⏳ Waiting for loading overlays to clear...")
            # Wait for the dimmer/loader to be hidden
            wait.until(EC.invisibility_of_element_located((By.CLASS_NAME, "dimmer-holder")))
            
            save_continue_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[@title='Save & Continue']")
            ))
            
            # Use JS click to bypass potential remaining overlays
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", save_continue_btn)
            driver.execute_script("arguments[0].click();", save_continue_btn)
            print("✅ 'Save & Continue' clicked using JavaScript.")
        except Exception as e:
            print(f"❌ Failed to click Save & Continue: {e}")
        
        print("🎉 Section completed.")
        
        # ---------------------------------------------------------
        # PAGE 2: PROMOTERS / PARTNERS
        # ---------------------------------------------------------
        time.sleep(2)
        print("⏳ Filling Page 2: Promoters / Partners...")

        set_input(driver, wait.until(EC.presence_of_element_located((By.ID, "ffname"))),
          final_data["father_first"])
        set_input(driver, driver.find_element(By.ID, "pd_fmname"),
          final_data["father_middle"])

        set_input(driver, driver.find_element(By.ID, "pd_flname"),
          final_data["father_last"])

        angular_set_value(driver,driver.find_element(By.ID, "dob"),final_data["dob"])

        set_input(driver, driver.find_element(By.ID, "mbno"),
          final_data["mobile"])

        set_input(driver, driver.find_element(By.ID, "pd_email"),
          final_data["email"])

        # Hide map overlay first
        hide_address_map(driver)
        time.sleep(0.5)
        # Gender selection (Angular safe)
        #if final_data["gender"].lower() == "male":
        #    gender = wait.until(EC.presence_of_element_located(
        #        (By.XPATH, "//label[@for='radiomale']")))
        #elif final_data["gender"].lower() == "female":
        #    gender = wait.until(EC.presence_of_element_located((By.XPATH, "//label[@for='radiofemale']")))
        #else:
        #    gender = wait.until(EC.presence_of_element_located((By.XPATH, "//label[@for='radioother']")))

        #safe_js_click(driver, gender)
        #GENDER = final_data["radiogroup_1"]

        #if GENDER == "Value":
            #gender_radio = wait.until(EC.presence_of_element_located(
                #(By.ID, "radiomale")
                #))
        #elif GENDER == "F":
            #gender_radio = wait.until(EC.presence_of_element_located(
                #(By.ID, "radiofemale")
            #))
        #else:
            #gender_radio = wait.until(EC.presence_of_element_located(
            #(By.ID, "radioother")
            #))

        #driver.execute_script("""
        #arguments[0].scrollIntoView({block:'center'});
        #arguments[0].checked = true;
        #arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
        #    """, gender_radio)

        #print(" Gender selected successfully")

        gender_label = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//label[@for='radiomale']")))
        #gender_label_female = wait.until(EC.element_to_be_clickable((By.XPATH, "//label[@for='radiofemale']")))
        #gender_label_other = wait.until(EC.element_to_be_clickable((By.XPATH, "//label[@for='radioother']")))
        # Scroll into view and click it (triggers Angular model change)

        driver.execute_script("""
        arguments[0].scrollIntoView({block:'center'});
        arguments[0].click();
        """, gender_label)

        print(" Male gender selected successfully")
        
        set_input(driver, driver.find_element(By.ID, "dg"),final_data["designation"])
        
        # PIN CODE (MOST IMPORTANT)
        pin = wait.until(EC.element_to_be_clickable((By.ID, "pncd")))
        # Scroll & focus
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", pin)
        time.sleep(0.5)

        # Clear safely
        pin.click()
        pin.send_keys(Keys.CONTROL, "a")
        pin.send_keys(Keys.DELETE)
        time.sleep(0.3)

        # Type FULL pin continuously (NO blur in between)
        for ch in str(final_data["pin_code"]):
            pin.send_keys(ch)
            time.sleep(0.15)
        time.sleep(0.5)
        time.sleep(0.3)
        pin.send_keys(Keys.TAB)
        citizen_yes = wait.until(EC.presence_of_element_located((By.XPATH,"//label[@for='pd_cit_ind']//span[@class='switch-on']")))

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});",citizen_yes)
        time.sleep(0.4)

        driver.execute_script("arguments[0].click();", citizen_yes)
        time.sleep(0.5)

        print("✅ Citizen of India set to YES")
        print(f"✅ PIN entered fully: {final_data['pin_code']}")

        # ⏳ Wait for GST backend auto-fill
        wait.until(lambda d: d.find_element(By.ID, "pd_state").get_attribute("value") != "")
        wait.until(lambda d: d.find_element(By.NAME, "dst").get_attribute("value") != "")
        wait.until(lambda d: d.find_element(By.ID, "city").get_attribute("value") != "")

        print("✅ State / District / City auto-filled")

        # TRIGGER BLUR WITHOUT CLICK
        pin.send_keys(Keys.TAB)

        set_input(driver, driver.find_element(By.ID, "pd_locality"),
              final_data["locality"])

        set_input(driver, driver.find_element(By.ID, "pd_road"),final_data["road_street_res"])

        set_input(driver, driver.find_element(By.ID, "pd_bdname"),
              final_data["premises_name"])

        set_input(driver, driver.find_element(By.ID, "pd_bdnum"),
              final_data["building_no_res"])

        set_input(driver, driver.find_element(By.ID, "pd_flrnum"),
              final_data["floor_no_res"])

        set_input(driver, driver.find_element(By.ID, "pd_landmark"),
              final_data["landmark_res"])
        
        toggle_no = wait.until(EC.presence_of_element_located((By.XPATH, "//span[@data-ng-bind='trans.LBL_NO']")))

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});",toggle_no)
        time.sleep(0.3)

        driver.execute_script("arguments[0].click();", toggle_no)
        time.sleep(0.5)

        print("✅ Toggle set to NO")
        PHOTO_FILE = r"C:\Users\joyce\OneDrive\Pictures\freephoto.jpeg"
        def upload_authorized_signatory_photo(driver, photo_path):
            wait = WebDriverWait(driver, 30)

            photo = wait.until(EC.presence_of_element_located(
            (By.ID, "pd_upload")
            ))

            driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", photo
            )
            photo.send_keys(photo_path)

            time.sleep(2)
            print(" Photograph uploaded")

        print(" Document Upload started")
        upload_authorized_signatory_photo(driver, PHOTO_FILE)
        try:
            print("⏳ Waiting for loading overlays to clear...")
            # Wait for the dimmer/loader to be hidden
            wait.until(EC.invisibility_of_element_located((By.CLASS_NAME, "dimmer-holder")))
            
            save_continue_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[@title='Save & Continue']")
            ))
            
            # Use JS click to bypass potential remaining overlays
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", save_continue_btn)
            driver.execute_script("arguments[0].click();", save_continue_btn)
            print("✅ 'Save & Continue' clicked using JavaScript.")
        except Exception as e:
            print(f"❌ Failed to click Save & Continue: {e}")
        
        print("🎉 Section completed.")

        # ---------------------------------------------------------
        # PAGE 3 : AUTHORIZED SIGNATORY / REPRESENTATIVE
        # ---------------------------------------------------------
        print("⏳ Processing Authorized Signatory / Representative...")
        
        primary_auth = wait.until(EC.presence_of_element_located((By.ID, "auth_prim")))
        driver.execute_script("""arguments[0].scrollIntoView({block:'center'});""", primary_auth)
        time.sleep(0.5)

        if not primary_auth.is_selected():
            driver.execute_script("""arguments[0].click();""", primary_auth)
        time.sleep(0.5)

        print("✅ Primary Authorized Signatory checked")

        def set_input_p3(driver, by_locator, value, timeout=20):
            el = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable(by_locator)
            )   
            el.clear()
            el.send_keys(value)

        def click_if_not_selected(driver, by_locator):
            el = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located(by_locator)
            )
            if not el.is_selected():
                driver.execute_script("arguments[0].click();", el)

        PAGE2_HAS_AUTH_SIGNATORY = final_data["Also Authorized Signatory"]
        IS_PRIMARY_AUTH = final_data["is_primary"]

        if PAGE2_HAS_AUTH_SIGNATORY == "true":
            print("Page-3 auto-filled by GST portal – no action required")
        else:
            print("Manually filling Page-3")

        # ---------------- Primary Authorized Signatory ----------------
        if IS_PRIMARY_AUTH == "true":
            click_if_not_selected(driver, (By.XPATH, "//input[@name='auth_prim']"))

        # ---------------- Name of Person ----------------
        set_input_p3(driver, (By.NAME, "fnm"), final_data["as_name_first"])
        set_input_p3(driver, (By.NAME, "as_mname"), final_data["as_name_middle"])
        set_input_p3(driver, (By.NAME, "as_lname"), final_data["as_name_last"])

        # ---------------- Father Name (NO By.ID) ----------------
        set_input_p3(driver, (By.XPATH, "//input[@name='ffname']"), final_data["as_father_first"])
        set_input_p3(driver, (By.NAME, "as_fmname"), final_data["as_father_middle"])
        set_input_p3(driver, (By.NAME, "as_flname"), final_data["as_father_last"])

        # ---------------- DOB ----------------
        dob = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.NAME, "dob")))
        driver.execute_script("""
        arguments[0].value = arguments[1];
        arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
        arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
        """, dob, final_data["dob"])

        #------------------DESIGNATION / STATUS----------
        set_input_p3(driver, (By.NAME, "dg"), final_data["as_designation"])
        #set_input_p3(driver, (By.XPATH, "mbno"), final_data["as_mobile"])
        #set_input_p3(driver, (By.XPATH, "em"), final_data["as_email"])
        #set_input(driver, (By.XPATH, "//input[@name='mbno']"), final_data["as_mobile"])
        #set_input(driver, (By.XPATH, "//input[@name='em']"), final_data["as_email"])
        set_input_p3(driver, (By.XPATH, "//input[@name='mbno']"), "6354977378")
        set_input_p3(driver, (By.XPATH, "//input[@name='em']"), "joylal0503@gamil.com")

        #-----------------DIN NUMBER (REQUIRED IF DIRECTOR)--------------
        set_input_p3(driver, (By.NAME, "din"), final_data["as_din"])
        #GENDER = final_data["radiogroup_1"]

        #if GENDER == "Value":
            #gender_radio = wait.until(EC.presence_of_element_located((By.ID, "radiomale")))
        #elif GENDER == "F":
            #gender_radio = wait.until(EC.presence_of_element_located((By.ID, "radiofemale")))
        #else:
            #gender_radio = wait.until(EC.presence_of_element_located((By.ID, "radioother")))

        #driver.execute_script("""
        #arguments[0].scrollIntoView({block:'center'});
        #arguments[0].checked = true;
        #arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
        #    """, gender_radio)

        #print(" Gender selected successfully")

        # Wait until Male label is clickable
        gender_label = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//label[@for='radiomale']"))
        )
        driver.execute_script("""
        arguments[0].scrollIntoView({block:'center'});
        arguments[0].click();
        """, gender_label)
        print(" Male gender selected successfully")

        #def set_citizen_and_identity(driver, citizen_india=True,
        #                    pan=None,
        #                    passport=None):
        #    """
        #    citizen_india = True  -> PAN required, Passport NOT required
        #    citizen_india = False -> Passport required
        #    """

        #    wait = WebDriverWait(driver, 30)

        #        #Hide map overlay (MANDATORY on Page-3)
        #    driver.execute_script("""
        #    let map = document.getElementById('map2');
        #    if (map) map.style.display = 'none';
        #    """)
         #   time.sleep(0.5)


         #   # Hidden checkbox behind toggle
         #   toggle = wait.until(EC.presence_of_element_located((By.ID, "as_cit_ind")))
        #    current = driver.execute_script("return arguments[0].checked;", toggle)
            
            # YES → checked, NO → unchecked
        #    if current != "true":
        #        driver.execute_script("""
        #            arguments[0].click();
        #            arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
        #        """, toggle)

        #    time.sleep(1)

            #if citizen_india:
                #if not final_data["as_pan"]:
                    #raise Exception("PAN is mandatory for Indian citizen")
                #pan_el = wait.until(EC.presence_of_element_located((By.NAME, "pan")))
                #driver.execute_script("""
                #arguments[0].value = arguments[1];
                #arguments[0].dispatchEvent(new Event('input',{bubbles:true}));
                #arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
                #arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
                #""", pan_el, final_data["as_pan"])
                #print(" Citizen = YES, PAN filled, Passport ignored")
            #else:
                #if not final_data["as_passport"]:
                    #raise Exception("Passport is mandatory for Foreigner")
                #pp = wait.until(EC.presence_of_element_located((By.ID, "ppno")))
                #driver.execute_script("""
                #arguments[0].value = arguments[1];
                #arguments[0].dispatchEvent(new Event('input',{bubbles:true}));
                #arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
                #arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
                #""", pp, final_data["as_passport"])
                #print(" Citizen = NO, Passport filled")

                #is_citizen = (final_data["toggle_3"] == "true")
                #if is_citizen:
                #    set_citizen_and_identity(driver, citizen_india=True, pan=final_data["as_pan"])
                #else:
                #    set_citizen_and_identity(driver, citizen_india=False, passport=final_data.get("as_passport", ""))

        time.sleep(3)
        #citizen_yes = wait.until(EC.presence_of_element_located((By.XPATH,"//label[@for='as_cit_ind']//span[@class='switch-on']")))
        #driver.execute_script("arguments[0].scrollIntoView({block:'center'});",citizen_yes)
        #time.sleep(0.4)
        #driver.execute_script("arguments[0].click();", citizen_yes)
        #time.sleep(0.5)

        #print("✅ Authorized Signatory citizen/resident set to YES")

        def set_citizen_yes_and_enter_pan(driver, final_data):
            wait = WebDriverWait(driver, 30)
            pan_value = final_data.get("as_pan")
            if not pan_value:
                raise Exception("PAN not found in final_data")

                # ================= SET TOGGLE = YES =================
            toggle = wait.until(EC.presence_of_element_located((By.ID, "as_cit_ind")))
            is_checked = driver.execute_script("return arguments[0].checked;", toggle)
            if not is_checked:
                driver.execute_script("arguments[0].click();", toggle)
                time.sleep(1)
                print("✅ Citizen toggle set to YES")

                # ================= WAIT FOR PAN TO ENABLE =================
            pan_el = wait.until(lambda d: d.find_element(By.ID, "pan"))
            wait.until(lambda d: pan_el.is_enabled())
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", pan_el)
            time.sleep(0.3)

            # ================= GST ANGULAR SAFE PAN SET =================
            driver.execute_script("""
                var el = arguments[0];
                var value = arguments[1];
                el.focus();
                // Clear existing value
                el.value = '';
                // Native setter (IMPORTANT for Angular)
                var setter = Object.getOwnPropertyDescriptor(
                    HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(el, value);

                // Fire Angular events
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
                """, pan_el, pan_value.upper())

            time.sleep(0.8)
            print(f"✅ PAN entered successfully: {pan_value}")

        set_citizen_yes_and_enter_pan(driver, final_data)
        set_input_p3(driver, (By.NAME, "pncd"), final_data["pin_code"])
        set_input_p3(driver, (By.NAME, "as_locality"), final_data["as_locality"])
        set_input_p3(driver, (By.NAME, "st"), final_data["as_road"])
        set_input_p3(driver, (By.NAME, "as_bdname"), final_data["as_premises"])
        set_input_p3(driver, (By.NAME, "bno"), final_data["as_bno"])
        
        USER_DOC_PREFERENCE = final_data["as_proof_type"]   
        AUTH_DOC_FILE = r"J:\Joyce\blank.pdf"
        PHOTO_FILE = r"C:\Users\joyce\OneDrive\Pictures\freephoto.jpeg"
        import os
        

        def select_authorized_signatory_proof(driver, preference):
            wait = WebDriverWait(driver, 30)

            dropdown = wait.until(EC.presence_of_element_located((By.ID, "as_up_type")))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", dropdown)

            select = Select(dropdown)
            preference = final_data["as_proof_type"]
            if preference == "LOAU":
                select.select_by_value("LOAU")
                print(" Selected: Letter of Authorisation")

            elif preference == "CRBC":
                select.select_by_value("CRBC")
                print(" Selected: Copy of resolution passed by BoD / Managing Committee")

            else:
                raise Exception(" Invalid document preference")

            # Trigger Angular
            driver.execute_script("""
                //arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
                //arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
                """, dropdown)

            time.sleep(1)
        def upload_authorized_signatory_doc(driver, file_path):
            wait = WebDriverWait(driver, 30)

            upload = wait.until(EC.presence_of_element_located(
                (By.XPATH, "//input[@type='file' and contains(@id,'as_upload')]")
            ))

            driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", upload
             )
            upload.send_keys(file_path)

            time.sleep(2)
            print(" Authorized signatory document uploaded")

        def upload_authorized_signatory_photo(driver, photo_path):
            wait = WebDriverWait(driver, 30)

            photo = wait.until(EC.presence_of_element_located(
            (By.ID, "as_upload_photo")
            ))

            driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", photo
            )
            photo.send_keys(photo_path)

            time.sleep(2)
            print(" Photograph uploaded")

        print(" Document Upload started")

        select_authorized_signatory_proof(driver, USER_DOC_PREFERENCE)
        upload_authorized_signatory_doc(driver, AUTH_DOC_FILE)
        upload_authorized_signatory_photo(driver, PHOTO_FILE)

        def click_gst_button(driver, action, timeout=30):
            wait = WebDriverWait(driver, timeout)
            xpath_map = {
                "save": "//button[@title='Save & Continue' and normalize-space()='Save & Continue']",
                "add_new": "//button[@title='Add New' and normalize-space()='Add New' and not(@disabled)]",
                "show_list": "//button[@title='Show List' and normalize-space()='Show List']",
                "back": "//a[@title='Back' and normalize-space()='Back']"
                }
            if action not in xpath_map:
                raise ValueError("Invalid action")
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_map[action])))
            driver.execute_script("""
                arguments[0].scrollIntoView({block:'center'});
                arguments[0].click();
            """, btn)
            time.sleep(2)
            print(f" {action.replace('_',' ').title()} clicked")

        click_gst_button(driver, "save")

        # ---------------------------------------------------------
        # PAGE 4: AUTHORIZED REPRESENTATIVE
        # ---------------------------------------------------------
        def set_authorized_rep_toggle(driver, wait, toggle_4):
            """
            toggle_4 = true  -> YES
            toggle_4 = false -> NO
            """

            try:
                auth_rep_input = wait.until(EC.presence_of_element_located((By.ID, "as_cit_ind")))

                # Check current state
                current = driver.execute_script("return arguments[0].checked;", auth_rep_input)

                if toggle_4 and not current:
                    driver.execute_script("arguments[0].click();", auth_rep_input)
                    print("✅ Authorized Representative set to YES")

                elif not toggle_4 and current:
                    driver.execute_script("arguments[0].click();", auth_rep_input)
                    print("✅ Authorized Representative set to NO")

                else:
                    print("ℹ Authorized Representative already correct")

                    time.sleep(0.8)

            except Exception as e:
                print("❌ Failed to set Authorized Representative toggle:", e)
        #set_authorized_rep_toggle(driver,wait,final_data.get("toggle_4", False))

        def set_authorized_representative_yes(driver):
            wait = WebDriverWait(driver, 30)

            # Scroll to the question label
            question_label = wait.until(EC.presence_of_element_located((
                By.XPATH,
                "//label[contains(text(),'Authorized Representative')]"
                )))
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});",
                question_label
            )
            time.sleep(0.5)

            # Click YES side of toggle (this is what GST listens to)
            yes_toggle = wait.until(EC.element_to_be_clickable((
                By.XPATH,
                "//label[.//span[contains(text(),'Yes')]]"
                )))

            driver.execute_script("""arguments[0].click();""", yes_toggle)
            time.sleep(1)
            print("✅ Authorized Representative toggle set to YES")
        set_authorized_representative_yes(driver)

        AUTH_REP_TYPE = final_data["radiogroup_2"]
        def angular_click(driver, element):driver.execute_script("""
                arguments[0].scrollIntoView({block:'center'});
                arguments[0].click();
                """, element)
        def angular_input(driver, element, value):
            driver.execute_script("""
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('input',{bubbles:true}));
            arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
            arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
            """, element, value)
        
        def select_dropdown_by_value(driver, element, value):
            driver.execute_script("""
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
            arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
            """, element, value)

        if AUTH_REP_TYPE == "TRP":
            trp_radio = wait.until(EC.element_to_be_clickable((By.ID, "trp")))
            angular_click(driver, trp_radio)

            #enrol = wait.until(EC.presence_of_element_located((By.ID, "ar_eid")))
            #angular_input(driver, enrol, GST_PRACTITIONER_ENROLMENT_ID)

            search_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(),'Search')]")
                ))
            angular_click(driver, search_btn)

            print(" GST Practitioner searched")
            time.sleep(3)
        else:
            other_label = wait.until(EC.element_to_be_clickable((By.XPATH,"//label[normalize-space()='Other']")))
            driver.execute_script("""
            arguments[0].scrollIntoView({block:'center'});
            arguments[0].click();
            """, other_label)

            time.sleep(2)
            print(" Other Authorized Representative selected")
            angular_click(driver, other_label)
            time.sleep(1)

            angular_input(driver, wait.until(EC.presence_of_element_located((By.ID, "ar_fname"))),
                  final_data["rep_name_first"])

            angular_input(driver, driver.find_element(By.ID, "ar_mname"),
                  final_data["rep_name_middle"])

            angular_input(driver, driver.find_element(By.ID, "ar_lname"),
                  final_data["rep_name_last"])

            select_dropdown_by_value(
            driver,
            driver.find_element(By.ID, "ar_des"),
            final_data["rep_designation"]
            )

            angular_input(driver, driver.find_element(By.ID, "ar_mbno"),
                  final_data["rep_mobile"])

            angular_input(driver, driver.find_element(By.ID, "ar_em"),
                  final_data["rep_email"])

            angular_input(driver, driver.find_element(By.ID, "pan"),
                  final_data["rep_pan"])

            #angular_input(driver, driver.find_element(By.ID, "ar_tlphnostd"),final_data["rep_telephone"])

            #angular_input(driver, driver.find_element(By.ID, "tlphno"),final_data["telephone"])

            #if final_data["fax_no"]:
                #angular_input(driver, driver.find_element(By.ID, "ar_fxno"),
                      #final_data["fax_std"])
                #angular_input(driver, driver.find_element(By.ID, "fxno"),
                      #final_data["fax_no"])

            print("Authorized Representative details filled")
        click_gst_button(driver, "save")

        # ---------------------------------------------------------
        # PAGE 5: PRINCIPAL PLACE OF BUSINESS
        # ---------------------------------------------------------
        print("⏳ Filling Page 5: Principal Place of Business...")
        
        pin = wait.until(EC.presence_of_element_located((By.NAME, "pncd")))
        driver.execute_script("""
            arguments[0].scrollIntoView({block:'center'});
            arguments[0].value = '';
            arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
            """, pin)
        time.sleep(0.3)
        pin.send_keys(final_data["ppb_pin"])
        driver.execute_script("""
        arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
        arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));
        """, pin)

        wait.until(lambda d: d.find_element(By.NAME, "dst").get_attribute("value").strip() != "")
        wait.until(lambda d: d.find_element(By.NAME, "loc").get_attribute("value").strip() != "")
        print("✅ GST accepted PIN (District & City auto-filled)")
        time.sleep(0.5)

        def angular_input_el(driver, element, value):
            driver.execute_script("""
            arguments[0].removeAttribute('readonly');
            arguments[0].removeAttribute('disabled');
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('input',{bubbles:true}));
            arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
            arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
            """, element, value)

        angular_input_el(driver, driver.find_element(By.ID, "ppbzdtls_locality"), final_data["ppb_locality"])
        angular_input_el(driver, driver.find_element(By.ID, "st"), final_data["ppb_road"])
        angular_input_el(driver, driver.find_element(By.ID, "bp_bdname"), final_data["ppb_premises"])
        angular_input_el(driver, driver.find_element(By.ID, "bno"), final_data["ppb_bno"])
        angular_input_el(driver, driver.find_element(By.ID, "bp_flrnum"), final_data["ppb_floor"])
        angular_input_el(driver, driver.find_element(By.ID, "ppbzdtls_landmark"), final_data["ppb_landmark"])

        poss = Select(driver.find_element(By.ID, "bp_buss_poss"))
        poss.select_by_value(final_data["ppb_possession_type"])
        driver.execute_script("""arguments[0].dispatchEvent(new Event('change',{bubbles:true}));""", driver.find_element(By.ID, "bp_buss_poss"))
        print(" Nature of possession selected")
        def select_angular_dropdown_page5(driver, by_locator, value, timeout=30):
            el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located(by_locator))
            driver.execute_script("arguments[0].scrollIntoView(true);", el)
            Select(el).select_by_value(value)
            driver.execute_script("""
            arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
            """, el)

        time.sleep(5)
        #select_angular_dropdown_page5(driver,(By.ID, "stj"), final_data["sector_circle"])
        #WebDriverWait(driver, 10).until(lambda d: d.find_element(By.ID, "stj").get_attribute("value") == final_data["sector_circle"])
        select_angular_dropdown_page5(driver,(By.ID, "stj"),"GJ001")
        WebDriverWait(driver, 10).until(lambda d: d.find_element(By.ID, "stj").get_attribute("value") == "GJ001")
        

        select_angular_dropdown_page5(driver,(By.ID, "comcd"), "WS")
        
        # Wait for option helper from dummy18
        from selenium.common.exceptions import StaleElementReferenceException
        def wait_for_option_value(driver, wait, select_id, value, timeout=20):
            def _option_present(d):
                try:
                    sel = Select(d.find_element(By.ID, select_id))
                    return any(opt.get_attribute("value") == value for opt in sel.options)
                except StaleElementReferenceException:
                    return False
            wait.until(_option_present)

        def select_dropdown_by_value_angular(driver, wait, select_id, value):
            el = wait.until(EC.presence_of_element_located((By.ID, select_id)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.3)
            sel = Select(el)
            sel.select_by_value(value)
            driver.execute_script("""
                arguments[0].dispatchEvent(new Event('change', {bubbles:true}));
                arguments[0].dispatchEvent(new Event('blur', {bubbles:true}));
                """, el)
            print(f"✅ {select_id} selected → {value}")
            time.sleep(0.5)

        wait_for_option_value(driver, wait, "divcd", final_data["center_division"])
        select_dropdown_by_value_angular(driver, wait, "divcd", final_data["center_division"])

        wait_for_option_value(driver, wait, "rgcd", final_data["center_range"])
        select_dropdown_by_value_angular(driver, wait, "rgcd", final_data["center_range"])

        wait_for_option_value(driver,wait,"bp_up_type",final_data["ppb_proof_doc"])
        select_dropdown_by_value_angular(driver,wait,"bp_up_type",final_data["ppb_proof_doc"])

        driver.execute_script("""
            arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
            arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
            """, driver.find_element(By.ID, "bp_up_type"))
        print(" Nature of possession set to OWN")
        driver.find_element(By.ID, "bp_upload").send_keys(r"J:\Joyce\blank.pdf")
        print(" Address proof uploaded")

        for bid in ["bp_ck_BWH", "bp_ck_EXP", "bp_ck_IMP"]:
            cb = driver.find_element(By.ID, bid)
            driver.execute_script("arguments[0].click();", cb)
            print(" Nature of business selected")

            def set_toggle_yes_no(driver, toggle_id, value):
                checkbox = driver.find_element(By.ID, toggle_id)
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", checkbox)
                time.sleep(0.3)
                current_state = checkbox.is_selected()
                if current_state != value:
                    driver.execute_script("""
                    arguments[0].click();
                    arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
                    """, checkbox)
                    print(f"✅ Toggle {toggle_id} set to → {'YES' if value else 'NO'}")
                else:
                    print(f"ℹ️ Toggle {toggle_id} already → {'YES' if value else 'NO'}")
                    time.sleep(0.5)

            set_toggle_yes_no(driver,"bp_add",final_data["toggle_4"])
            time.sleep(2)

        save_btn = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.XPATH, "//button[@title='Save & Continue']")))
        driver.execute_script("arguments[0].click();", save_btn)

        print(" PAGE-5 COMPLETED SUCCESSFULLY")
        time.sleep(2)
        
        # ---------------------------------------------------------
        # PAGE 6: ADDITIONAL PLACE OF BUSINESS
        # ---------------------------------------------------------
        time.sleep(3)
        ctr = driver.find_element(By.ID, "abp_ctr")
        driver.execute_script("""
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('input',{bubbles:true}));
            arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
            """, ctr, final_data["apb_count"])

        print(" Additional place count entered")
        time.sleep(2)
        # ================================================
        # CLICK ADD NEW
        # ===============================================

        add_new = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Add New')]")))
        driver.execute_script("arguments[0].click();", add_new)
        print(" Add New clicked")
        time.sleep(3)

        # ================================================================
        # PINCODE (MANDATORY GST FLOW)
        # ===============================================================

        pin = WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.ID, "pncd")))
        pin.click()
        pin.clear()

        for ch in final_data["apb_pin"]:
            pin.send_keys(ch)
            time.sleep(0.25)

        WebDriverWait(driver, 20).until(lambda d: d.find_element(By.ID, "dst").get_attribute("value") != "")
        print(" PIN accepted by GST")

        # ==================================================
            # ADDRESS (PAGE-6 IDS ONLY)
        # ==================================================
        def js_fill(id_, value):
           el = driver.find_element(By.ID, id_)
           driver.execute_script("""
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('input',{bubbles:true}));
            arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
            """, el, value)

        js_fill("ap_locality", final_data["apb_locality"])
        js_fill("st", final_data["apb_road"])
        js_fill("ap_bdname", final_data["apb_premises"])
        js_fill("abp_bdnum", final_data["apb_bno"])
        js_fill("ap_flrnum", final_data["apb_floor"])
        js_fill("ap_landmark", final_data["apb_landmark"])

        print(" Address details filled (Page-6)")

        # =============================================
        # CONTACT DETAILS
        # ===========================================
        js_fill("ap_email", final_data["apb_email"])
        js_fill("mbno", final_data["apb_mobile"])

        print(" Contact details filled")

        # ================================================
        # NATURE OF POSSESSION
        # ================================================
        Select(driver.find_element(By.ID, "psnt")).select_by_value(final_data["apb_possession_type"])
        driver.find_element(By.ID, "psnt").dispatchEvent = True
        print(" Nature of possession selected")

        # =======================================================
        # DOCUMENT UPLOAD
        # =======================================================
        Select(driver.find_element(By.ID, "ap_up_type")).select_by_value(final_data["apb_proof_doc"])
        #driver.find_element(By.ID, "ap_upload").send_keys(final_data["apb_file"])
        driver.execute_script("""
            arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
            arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
            """, driver.find_element(By.ID, "ap_up_type"))
        driver.find_element(By.ID, "ap_upload").send_keys(r"C:\Users\joyce\OneDrive\Pictures\freephoto.jpeg")
        print(" Address proof uploaded")

        # ===========================================================
        # NATURE OF BUSINESS ACTIVITY
        # ===========================================================

        from selenium.common.exceptions import NoSuchElementException

        def set_checkbox(driver, checkbox_id, should_be_checked):
            try:
                checkbox = driver.find_element(By.ID, checkbox_id)
            except NoSuchElementException:
                print(f"⚠️ {checkbox_id} not present on page — skipped")
                return

            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", checkbox)
            time.sleep(0.2)
            current_state = checkbox.is_selected()
            if current_state != should_be_checked:
                driver.execute_script("""
                    arguments[0].click();
                    arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
                """, checkbox)
                print(f"✅ {checkbox_id} set to → {should_be_checked}")
            else:
                print(f"ℹ️ {checkbox_id} already → {should_be_checked}")

            time.sleep(0.2)
        checkbox_mapping = {
            "apb_bonded_warehouse": "bp_ck_BWH",
            "apb_eou": "bp_ck_EOU",
            "apb_export": "bp_ck_EXP",
            "apb_factory": "bp_ck_FMF",
            "apb_import": "bp_ck_IMP",
            "apb_services": "bp_ck_SOS",
            "apb_leasing": "bp_ck_LBU",
            "apb_office": "bp_ck_OSO",
            "apb_recipient": "bp_ck_SRE",
            "apb_retail": "bp_ck_RBU",
            "apb_warehouse": "bp_ck_WHD",
            "apb_wholesale": "bp_ck_WBU",
            "apb_works_contract": "bp_ck_WCO",
            "apb_others": "bp_ck_OTH"
            }

        for key, checkbox_id in checkbox_mapping.items():
            set_checkbox(driver, checkbox_id, final_data.get(key, False))

        # =======================================================
        # SAVE & CONTINUE
        # ==========================================================
        save_btn = WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Save')]")))
        driver.execute_script("arguments[0].click();", save_btn)
        # =================================================================
        # CONTINUE
        # ===============================================================
        continue_btn = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((
                By.XPATH,
                "//button[@data-ng-bind='trans.LBL_CONTINUE' and not(@disabled)]"
            ))
            )
        driver.execute_script("""
        arguments[0].scrollIntoView({block:'center'});
        arguments[0].click();
        """, continue_btn)

        print(" Continue button clicked")
        time.sleep(2)

        # ---------------------------------------------------------
        # PAGE 7: GOODS AND SERVICES (HSN/SAC)
        # ---------------------------------------------------------
        print("⏳ Filling Page 7: Goods and Services...")
        
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "gs_hsn_value")))
        print(" Page-7 (Goods / Commodities) loaded")
        time.sleep(2)
        def select_autocomplete(driver, input_id, code):
            if not code:
                return

            wait = WebDriverWait(driver, 30)
            input_box = wait.until(EC.element_to_be_clickable((By.ID, input_id)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", input_box)

            # Clear properly
            input_box.click()
            input_box.send_keys(Keys.CONTROL, "a")
            input_box.send_keys(Keys.DELETE)
            time.sleep(0.3)

            # TYPE FULL CODE FIRST
            for ch in str(code):
                input_box.send_keys(ch)
                time.sleep(0.25)

            # WAIT FOR AUTOCOMPLETE DROPDOWN
            time.sleep(2)

            # SELECT FIRST SUGGESTION ONLY ONCE
            input_box.send_keys(Keys.ARROW_DOWN)
            time.sleep(0.3)
            input_box.send_keys(Keys.ENTER)

            # LET GST ANGULAR LOCK VALUE
            time.sleep(1.5)

            print(f"✅ {input_id} selected → {code}")

                # =================================================
                # HSN (GOODS)
                # =================================================
        select_autocomplete(driver,"gs_hsn_value",final_data.get("hsn_search"))

        # =================================================
        # SWITCH TO SERVICES TAB
        # =================================================

        services_tab = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//a[@href='#services']")))
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});arguments[0].click();",services_tab)
        time.sleep(2)
        print(" Services tab clicked")
        select_autocomplete(driver,"gs_ssn_value",final_data.get("sac_search"))
        print(" PAGE-7 (GOODS & SERVICES) COMPLETED")

        save_btn = WebDriverWait(driver, 30).until(EC.element_to_be_clickable(
        (By.XPATH, "//button[@data-ng-bind='trans.LBL_SAVE_CONTINUE']")))
        driver.execute_script("""arguments[0].scrollIntoView({block:'center'});arguments[0].click();""", save_btn)

        print("PAGE-7 (SERVICES) COMPLETED → PAGE-8")

        # ---------------------------------------------------------
        # PAGE 8: STATE SPECIFIC INFORMATION
        # ---------------------------------------------------------
        print("⏳ Filling Page 8: State Specific...")
        
        eb_select = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "ebcd")))
        Select(eb_select).select_by_value(final_data["electricity_board"])
        driver.execute_script("""arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
                              arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));""", eb_select)
        print(" Electricity Board selected")
        time.sleep(1)

        def angular_set_p8(driver, element, value):
            driver.execute_script("""
                arguments[0].removeAttribute('readonly');
                arguments[0].value = arguments[1];
                arguments[0].dispatchEvent(new Event('input',{bubbles:true}));
                arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
                arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
            """, element, value)

        ca_input = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "canum")))
        angular_set_p8(driver, ca_input, final_data["consumer_number"])
        print(" CA Number filled")

        ec_tax = driver.find_element(By.ID, "ec_tax")
        angular_set_p8(driver, ec_tax, final_data["prof_tax_ec"])
        print(" Professional Tax EC No filled")

        rc_tax = driver.find_element(By.ID, "rc_tax")
        angular_set_p8(driver, rc_tax, final_data["prof_tax_rc"])
        print(" Professional Tax RC No filled")

        lic_no = driver.find_element(By.ID, "lic_no")
        angular_set_p8(driver, lic_no, final_data["state_excise_lic"])
        print(" State Excise License No filled")

        per_lic = driver.find_element(By.ID, "per_lic_no")
        angular_set_p8(driver, per_lic, final_data["excise_person_name"])
        print(" Excise License Holder Name filled")

        save_btn = WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.XPATH, "//button[@title='Save & Continue']")))
        driver.execute_script("""
            arguments[0].scrollIntoView({block:'center'});
            arguments[0].click();
            """, save_btn)

        print(" PAGE-8 COMPLETED SUCCESSFULLY")

        # ---------------------------------------------------------
        # PAGE 9: AADHAAR AUTHENTICATION
        # ---------------------------------------------------------
        print("⏳ Handling Aadhaar Authentication...")
        aadhaar_checkboxes = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//input[contains(@id,'chkboxop')]")))
        print(f"Found {len(aadhaar_checkboxes)} Aadhaar rows")

        aadhaar_chk = aadhaar_checkboxes[0]
        driver.execute_script("""
            arguments[0].scrollIntoView({block:'center'});
            arguments[0].removeAttribute('disabled');
            arguments[0].click();
            """, aadhaar_chk)

        print("✅ Aadhaar Authentication checkbox clicked properly")
        time.sleep(1)

        try:
            print("⏳ Waiting for loading overlays to clear...")
            wait.until(EC.invisibility_of_element_located((By.CLASS_NAME, "dimmer-holder")))
            save_continue_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[@title='Save & Continue']")
            ))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", save_continue_btn)
            driver.execute_script("arguments[0].click();", save_continue_btn)
            print("✅ 'Save & Continue' clicked using JavaScript.")
        except Exception as e:
            print(f"❌ Failed to click Save & Continue: {e}")
        
        print("🎉 Section completed.")

        # ---------------------------------------------------------
        # PAGE 10: VERIFICATION
        # ---------------------------------------------------------
        print("⏳ Finalizing Verification...")
        WebDriverWait(driver, 40).until(EC.presence_of_element_located((By.ID, "authveri")))
        print(" Page-10 loaded")

        verify_chk = driver.find_element(By.ID, "authveri")
        if not verify_chk.is_selected():
            driver.execute_script("""
                arguments[0].scrollIntoView({block:'center'});
                arguments[0].click();
            """, verify_chk)
            print(" Declaration accepted")
            time.sleep(1)

        auth_sign = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "authsign")))
        select_sign = Select(auth_sign)
        select_sign.select_by_index(1)   
        driver.execute_script("""
        arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
        arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
        """, auth_sign)
        print(" Authorized Signatory selected")

        place_input = driver.find_element(By.ID, "veriPlace")
        driver.execute_script("""
        arguments[0].value = arguments[1];
        arguments[0].dispatchEvent(new Event('input',{bubbles:true}));
        arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
        arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));
        """, place_input, final_data["place"])
        print(" Place entered")

        submit_btn = WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Submit with EVC')]")))
        driver.execute_script("""
        arguments[0].scrollIntoView({block:'center'});
        arguments[0].click();
        """, submit_btn)

        print(" APPLICATION SUBMITTED — EVC TRIGGERED")
        input("Stay open press enter to exit..")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        traceback.print_exc()
        input("Error occurred. Press ENTER to close...")
    finally:
        driver.quit()
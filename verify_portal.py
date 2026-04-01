import requests
import sys

BASE_URL = "http://127.0.0.1:5000"
USER_EMAIL = "goutham.student@gmail.com"
USER_PASS = "testpassword"

def verify():
    session = requests.Session()
    
    # 1. Login
    print(f"Logging in as {USER_EMAIL}...")
    login_data = {
        "role": "student",
        "email": USER_EMAIL,
        "password": USER_PASS
    }
    resp = session.post(f"{BASE_URL}/login", data=login_data, allow_redirects=True)
    if "Welcome back" not in resp.text:
        print("Login failed!")
        # print(resp.text)
        return False
    print("Login successful.")

    # 2. Check Profile Tab (Should NOT have KPIs/Chart)
    print("Checking Profile tab...")
    resp = session.get(f"{BASE_URL}/student?tab=profile")
    if "CGPA" in resp.text and "KPI Stats moved here" in resp.text:
        print("FAIL: KPI stats found in Profile tab.")
        # We check for the specific marker or keyword that should only be in Academics
    else:
        print("SUCCESS: KPI stats not found in Profile tab.")

    # 3. Check Academics Tab (SHOULD have KPIs/Chart)
    print("Checking Academics tab...")
    resp = session.get(f"{BASE_URL}/student?tab=academics")
    if "CGPA" in resp.text and "Semester Grade Point Average (SGPA)" in resp.text:
        print("SUCCESS: KPI stats and chart found in Academics tab.")
    else:
        print("FAIL: KPI stats or chart missing from Academics tab.")

    # 4. Test URL Validation (Invalid)
    print("Testing invalid URL validation...")
    profile_data = {
        "form_type": "profile",
        "name": "Goutham",
        "contact_email": USER_EMAIL,
        "phone": "9876543210",
        "parent_phone": "9876543211",
        "address": "123 Street",
        "department": "CSE",
        "mentor_name": "Dr. Smith",
        "leetcode_url": "https://google.com",
        "github_url": "invalid-gh",
        "linkedin_url": "https://linkedin.com/user"
    }
    resp = session.post(f"{BASE_URL}/student", data=profile_data, allow_redirects=False)
    print(f"POST /student status: {resp.status_code}, location: {resp.headers.get('Location')}")
    if resp.status_code == 302:
        resp = session.get(f"{BASE_URL}{resp.headers.get('Location')}")
        
    if "Invalid LeetCode URL" in resp.text or "Invalid GitHub URL" in resp.text or "Invalid LinkedIn URL" in resp.text:
        print("SUCCESS: Validation caught invalid URLs.")
    else:
        print("FAIL: Validation did not catch invalid URLs.")
        print("DEBUG: Response length:", len(resp.text))

    # 5. Test URL Validation (Valid)
    print("Testing valid URL validation...")
    profile_data["leetcode_url"] = "https://leetcode.com/u/goutham/"
    profile_data["github_url"] = "https://github.com/goutham"
    profile_data["linkedin_url"] = "https://linkedin.com/in/goutham"
    resp = session.post(f"{BASE_URL}/student", data=profile_data, allow_redirects=False)
    print(f"POST /student status: {resp.status_code}, location: {resp.headers.get('Location')}")
    if resp.status_code == 302:
        resp = session.get(f"{BASE_URL}{resp.headers.get('Location')}")

    if "Profile & Professional Links updated" in resp.text:
        print("SUCCESS: Valid URLs accepted.")
    else:
        print("FAIL: Valid URLs rejected or update failed.")
        print("DEBUG: Response length:", len(resp.text))
        # print(resp.text)

    return True

if __name__ == "__main__":
    if not verify():
        sys.exit(1)

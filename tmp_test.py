import requests

session = requests.Session()
# Login
resp = session.post('http://127.0.0.1:5000/login', data={'role': 'student', 'email': 'test.student@gmail.com', 'password': 'password123'})

# Post invalid profile data
data = {
    'form_type': 'profile',
    'name': 'Test Student',
    'contact_email': 'test@example.com',
    'phone': '1234567890',
    'parent_phone': '0987654321',
    'address': 'Address',
    'department': 'CS',
    'mentor_name': 'Mentor1',
    'scholar_type': 'Day Scholar',
    'leetcode_url': 'invalid_leetcode',
    'github_url': 'invalid_github',
    'linkedin_url': 'invalid_linkedin',
    'batch': '2023',
    'enrollment_no': 'E123',
    'register_no': 'R123',
    'dte_umis_reg_no': 'DTE123',
    'application_no': 'APP123',
    'admission_no': 'ADM123',
    'father_name': 'Father',
    'mother_name': 'Mother',
    'gender': 'Male',
    'dob': '2000-01-01',
    'community': 'BC',
    'religion': 'Hindu',
    'nationality': 'Indian',
    'mother_tongue': 'Tamil',
    'blood_group': 'O+',
    'aadhar_no': '123456789012',
    'parent_occupation': 'Business',
    'parent_income': '100000'
}

resp2 = session.post('http://127.0.0.1:5000/student', data=data)
if "Invalid LeetCode URL" in resp2.text and "Invalid GitHub URL" in resp2.text and "Invalid LinkedIn URL" in resp2.text:
    print("SUCCESS: Validation errors displayed correctly.")
else:
    print("FAILED: Validation errors not found in HTML output.")

# Post valid profile data
data['leetcode_url'] = 'https://leetcode.com/u/test/'
data['github_url'] = 'https://github.com/test'
data['linkedin_url'] = 'https://linkedin.com/in/test'

resp3 = session.post('http://127.0.0.1:5000/student', data=data)
if "Profile & Professional Links updated" in resp3.text:
    print("SUCCESS: Profile updated successfully with valid URLs.")
else:
    print("FAILED: Profile not updated.")

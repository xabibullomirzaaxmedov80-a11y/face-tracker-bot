import requests

token = "rnd_Ftw6g1bIsr9SB0tKxjqe8gu6PNi2"
headers = {
    "accept": "application/json",
    "authorization": f"Bearer {token}"
}

# 1. Get Owner ID
owners_url = "https://api.render.com/v1/owners"
resp = requests.get(owners_url, headers=headers)
owners = resp.json()
owner_id = owners[0]['owner']['id']

# 2. Create Service
url = "https://api.render.com/v1/services"
payload = {
    "type": "web_service",
    "name": "face-tracker",
    "ownerId": owner_id,
    "repo": "https://github.com/xabibullomirzaaxmedov80-a11y/face-tracker-bot",
    "autoDeploy": "yes",
    "branch": "master",
    "serviceDetails": {
        "env": "python",
        "plan": "free",
        "region": "oregon",
        "envSpecificDetails": {
            "buildCommand": "pip install -r requirements.txt",
            "startCommand": "gunicorn app:app"
        }
    }
}

headers["content-type"] = "application/json"

response = requests.post(url, json=payload, headers=headers)
print("Create Status:", response.status_code)
print("Create Response:", response.text)

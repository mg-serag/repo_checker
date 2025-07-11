import json
import os
import time
import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from diskcache import FanoutCache

from convert import process_json_file

# --- Labeling Tool Configuration ---
from config_utils import get_lt_token, get_swe_token
LT_TOKEN = get_lt_token()
PERSONAL_LT_TOKEN = get_lt_token()
SWE_TOKEN = get_swe_token()

REPO_LIST = [
    "MetaMask/metamask-mobile",
]

# 1) cookies & headers helpers
_AUTH_COOKIES = {"auth_token": SWE_TOKEN, "eval_access_token": LT_TOKEN}
_DEFAULT_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

# Helper comments above were accidentally executed. Removed invalid global `return` statement.
# All request calls below now pass cookies via `_AUTH_COOKIES` for proper authentication.

def _check_json_response(res):
    """Validate SWE-Bench API response is JSON; return parsed JSON or None."""
    if "application/json" not in res.headers.get("Content-Type", ""):
        print("Auth failed – got HTML login page (check tokens). Preview: ")
        print(res.text[:200])
        return None
    try:
        return res.json()
    except json.JSONDecodeError:
        print("❌ Failed to parse JSON response")
        return None

def get_repo_details(repo_name):
    url = f"https://swe-bench-plus.turing.com/api/jobs/get?topic=get_relevant_prs&repo_id={repo_name}"
    response = requests.get(url, cookies=_AUTH_COOKIES, headers=_DEFAULT_HEADERS)
    return _check_json_response(response) or {}

def get_job_id(repo_name):
    try:
        response = get_repo_details(repo_name)
        statuses = ["COMPLETED", "IN_PROGRESS", "NEW"]
        if response:
            return response['id'] if response["status"] in statuses else None
        else:
            return None
    except Exception as e:
        print(f"Error checking repo {repo_name}: {e}")
        return None

def start_job(repo_name):
    url = f"https://swe-bench-plus.turing.com/api/jobs"
    data = {
        "topic": "get_relevant_prs",
        "payload": {
  "repo_id": repo_name,
  "run_with_dockerfile": True,
  "repo": {
    "repo": repo_name,
    "repo_id": repo_name,
    "language": "TypeScript",
    "dockerfile": None,
    "updated_by_user_email": None
  },
  "repo_name": repo_name,
  "min_test_files": 1,
  "max_non_test_files": 100,
  "max_prs": 1000
},
    }
    response = requests.post(url, cookies=_AUTH_COOKIES, headers=_DEFAULT_HEADERS, json=data)
    payload = _check_json_response(response)
    return payload.get("jobId") if payload else None

def get_job_status(job_id):
    url = f"https://swe-bench-plus.turing.com/api/jobs/{job_id}"
    response = requests.get(url, cookies=_AUTH_COOKIES, headers=_DEFAULT_HEADERS)
    payload = _check_json_response(response)
    return payload.get("status", "UNKNOWN") if payload else "FAILED"


def get_pr_list(repo):
    with FanoutCache("cache") as cache:
        response = cache.get(f'{repo}_response')
        if response is None:
            url = f'https://swe-bench-plus.turing.com/repos/{repo}'
            response = requests.get(url, cookies=_AUTH_COOKIES, headers={"Accept": "text/html"})
            if response.status_code == 200:
                cache.set(f'{repo}_response', response.text)
            response = response.text
        else:
            print(f'{repo} response found in cache')
    soup = BeautifulSoup(response, "html.parser")
    # get the script with the id __NEXT_DATA__ 
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None:
        print(f"{repo} doesn't exist")
        return []
    data = json.loads(script.text)
    return data["props"]["pageProps"]["rows"]


def create_lt_batch(repo_name, csv_file_name):
    url = f"https://eval.turing.com/api/batches/upload/rlhf-metadata"
    data = {
        "project_type": "rlhf",
    }
    files = {
        "file": open(csv_file_name, "rb")
    }
    response = requests.post(url, headers={"Authorization": f"Bearer {PERSONAL_LT_TOKEN}"}, data=data, files=files)
    file_link = response.json()["fileLink"]
    print(file_link)
    create_lt_batch_url = f"https://eval.turing.com/api/batches"
    data = {"name":repo_name,"folder":file_link,"description":"","status":"draft","file":{},
            "isRLHFFolder":False,"shouldShowSubfolder":False,"isRLHFProjectSuite":True,
            "project":{"id":41,"name":"Swe-bench-JS",
                       "status":"ongoing","projectType":"rlhf","readonly":False},
                       "projectId":41,"projectType":"rlhf"}
    response = requests.post(create_lt_batch_url, headers={"Authorization": f"Bearer {PERSONAL_LT_TOKEN}", "Content-Type": "application/json"}, json=data)
    batch_id = response.json()["id"]
    import_url = f"https://eval.turing.com/api/batches/{batch_id}/import-rlhf"
    response = requests.post(import_url, headers={"Authorization": f"Bearer {PERSONAL_LT_TOKEN}", "Content-Type": "application/json"}, json=data)
    return f"https://eval.turing.com/batches/{batch_id}/view"

def add_repo(repo_name):
    job_id = get_job_id(repo_name)
    if not job_id:
        job_id = start_job(repo_name)
    while get_job_status(job_id) != "COMPLETED":
        time.sleep(10)
    print(f"{repo_name} completed")
    pr_list = get_pr_list(repo_name)
    json_file_name = f"{repo_name}.json"
    json.dump(pr_list, open(json_file_name, "w"))
    process_json_file(json_file_name, f"./{repo_name}.csv")
    batch_url = create_lt_batch(repo_name, f"./{repo_name}.csv")
    return batch_url


def main():
    for repo in REPO_LIST:
        repo_name = repo.replace("/", "__")
        batch_url = add_repo(repo_name)
        print(f"{repo_name} batch created at {batch_url} Visit the LT to enable the batch")

if __name__ == "__main__":
    main()
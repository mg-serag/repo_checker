import json
import os
import time
import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from diskcache import FanoutCache
import argparse
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from config_utils import get_language_config, get_language_sheet_name, get_language_project_id, get_language_json_folder, get_language_csv_folder
from convert import convert_folder

from utils.lt_batch_utils import process_json_file

load_dotenv()
PERSONAL_LT_TOKEN = os.getenv("PERSONAL_LT_TOKEN")
SWE_TOKEN = os.getenv("SWE_TOKEN")
LT_TOKEN = os.getenv("LT_TOKEN")

REPO_LIST = [
    # "open-telemetry/opentelemetry-js",
    # "newrelic/node-newrelic",
    # "angular-eslint/angular-eslint",
    "Comfy-Org/ComfyUI_frontend",
    "renovatebot/renovate",
    "formbricks/formbricks",
    "Kilo-Org/kilocode",
    "simstudioai/sim",
    "unnoq/orpc",
    "monkeytypegame/monkeytype",
    "unjs/jiti",
    "naver/billboard.js",
    "colinhacks/zod",
    "line/tsr",
    "angular/components",
    "tus/tus-node-server",
    "brisa-build/brisa",
]

def get_repo_details(repo_name):
    url = f"https://swe-bench-plus.turing.com/api/jobs/get?topic=get_relevant_prs&repo_id={repo_name}"
    response = requests.get(url, headers={"Cookie": f"auth_token={SWE_TOKEN};eval_access_token={PERSONAL_LT_TOKEN}", "Content-Type": "application/json"})
    return response.json()

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
    response = requests.post(url, headers={"Cookie": f"auth_token={SWE_TOKEN};eval_access_token={PERSONAL_LT_TOKEN}", "Content-Type": "application/json"}, json=data)
    return response.json()["jobId"]

def get_job_status(job_id):
    url = f"https://swe-bench-plus.turing.com/api/jobs/{job_id}"
    response = requests.get(url, headers={"Cookie": f"auth_token={SWE_TOKEN};eval_access_token={PERSONAL_LT_TOKEN}", "Content-Type": "application/json"})
    return response.json()["status"]


def get_pr_list(repo):
    with FanoutCache("cache") as cache:
        response = cache.get(f'{repo}_response')
        if response is None:
            url = f'https://swe-bench-plus.turing.com/repos/{repo}'
            response = requests.get(url, headers={"Cookie": f"auth_token={SWE_TOKEN};eval_access_token={PERSONAL_LT_TOKEN}"})
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


def create_lt_batch(repo_name, csv_file_name, project_id):
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
            "project":{"id":project_id,"name":"Swe-bench-JS",
                       "status":"ongoing","projectType":"rlhf","readonly":False},
                       "projectId":project_id,"projectType":"rlhf"}
    response = requests.post(create_lt_batch_url, headers={"Authorization": f"Bearer {PERSONAL_LT_TOKEN}", "Content-Type": "application/json"}, json=data)
    batch_id = response.json()["id"]
    import_url = f"https://eval.turing.com/api/batches/{batch_id}/import-rlhf"
    response = requests.post(import_url, headers={"Authorization": f"Bearer {PERSONAL_LT_TOKEN}", "Content-Type": "application/json"}, json=data)
    return f"https://eval.turing.com/batches/{batch_id}/view"

def get_repos_from_sheet(sheet_name, creds_path, spreadsheet_key, count=10):
    """
    Fetches repositories from a Google Sheet based on specified criteria.
    """
    print(f"Fetching repositories from sheet: {sheet_name}")
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(creds_path, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)
        
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        # Filter based on criteria
        filtered_df = df[(df['Good PRs > 2'] == 'Yes') & (df['Added'] == 'No')]
        
        # Sort by 'Relevant PRs count'
        sorted_df = filtered_df.sort_values(by='Relevant PRs count', ascending=False)
        
        # Get top N repositories
        top_repos = sorted_df.head(count)['Repository'].tolist()
        print(f"Found {len(top_repos)} repositories to process.")
        return top_repos
        
    except Exception as e:
        print(f"Error fetching from Google Sheet: {e}")
        return []

def main():
    parser = argparse.ArgumentParser(description="Create LT batches from repositories.")
    parser.add_argument("target_language", help="The target language to process (e.g., JavaScript, Python).")
    parser.add_argument("--manual", nargs='+', help="A manual list of repositories to process (e.g., 'user/repo1 user/repo2').")
    parser.add_argument("--count", type=int, default=10, help="Number of top repositories to fetch from the sheet.")
    args = parser.parse_args()

    # Get language-specific configurations
    lang_config = get_language_config(args.target_language)
    sheet_name = get_language_sheet_name(args.target_language)
    project_id = get_language_project_id(args.target_language)
    json_folder = get_language_json_folder(args.target_language)
    csv_folder = get_language_csv_folder(args.target_language)

    # Create folders if they don't exist
    os.makedirs(json_folder, exist_ok=True)
    os.makedirs(csv_folder, exist_ok=True)

    repo_list = []
    if args.manual:
        repo_list = args.manual
        print(f"Using manual repository list: {repo_list}")
    else:
        creds_path = os.path.join(os.path.dirname(__file__), 'creds.json')
        from config_utils import get_spreadsheet_key
        spreadsheet_key = get_spreadsheet_key()
        repo_list = get_repos_from_sheet(sheet_name, creds_path, spreadsheet_key, args.count)

    for repo in repo_list:
        repo_name_safe = repo.replace("/", "__")
        
        # Get PRs from SWE Bench
        pr_list = get_pr_list(repo_name_safe)
        if not pr_list:
            continue
            
        json_file_path = os.path.join(json_folder, f"{repo_name_safe}.json")
        with open(json_file_path, 'w') as f:
            json.dump(pr_list, f)
        print(f"Saved PRs to {json_file_path}")

    # Convert all JSON files in the folder to CSV
    convert_folder(json_folder, csv_folder)

    # Upload CSVs to LT
    for csv_file in os.listdir(csv_folder):
        if csv_file.endswith(".csv"):
            repo_name_safe = csv_file.replace('.csv', '')
            csv_file_path = os.path.join(csv_folder, csv_file)
            batch_url = create_lt_batch(repo_name_safe, csv_file_path, project_id)
            print(f"Batch for {repo_name_safe} created at {batch_url}. Visit the LT to enable the batch.")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
SWE-Bench Batch Creator V2
---------------------------
Combines the structure and logic of swe_bench_runner.py with spreadsheet functionality.
Can process repositories from a manual REPO_LIST or fetch them from Google Sheets.

Usage Options:
1. Direct execution (modify TARGET_LANGUAGE and REPO_LIST in configuration section):
   python create_repo_batches_v2.py

2. Command line with target language:
   python create_repo_batches_v2.py JavaScript

3. Command line with manual repository list:
   python create_repo_batches_v2.py JavaScript --manual user/repo1 user/repo2

4. Command line with custom count:
   python create_repo_batches_v2.py JavaScript --count 20

5. Command line with upload mode:
   python create_repo_batches_v2.py JavaScript --upload-mode Good
"""

import json
import os
import time
import requests
from bs4 import BeautifulSoup
from diskcache import FanoutCache
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import csv # Added for compare_prs_and_skip_if_identical
from datetime import datetime
import sys
from urllib.parse import urlparse

# Token & config helpers
from config_utils import (
    get_lt_token,
    get_swe_token,
    get_language_json_folder,
    get_language_csv_folder,
    get_language_config,
    get_language_sheet_name,
    get_language_project_id,
    get_spreadsheet_key,
)

from convert import process_json_file



# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Tokens (read once at import)
PERSONAL_LT_TOKEN = get_lt_token()  # Same as LT_TOKEN
LT_TOKEN = PERSONAL_LT_TOKEN        # Alias for clarity
SWE_TOKEN = get_swe_token()

# Default language settings (adjust if needed)
TARGET_LANGUAGE = "C/C++"

# Upload filtering mode - controls which PRs to include in the final CSV
# All: Upload all PRs found in the JSON file (only do deduplication step to remove PRs already in SWE Bench)
# Good: Filter to include only Good PRs (PRs marked as "Good PR" in the PR reports)
# Logical: Filter to include all PRs in the PR report whether the agent judged them as good or bad
UPLOAD_MODE = 'Logical'  # Options: 'All', 'Good', 'Logical'

# Default count for spreadsheet repositories
TARGET_REPO_COUNT = 10

# Use manual repos or spreadsheet
USE_MANUAL_REPOS = False  # Set to False to use spreadsheet

# Manual repository list (only used if USE_MANUAL_REPOS = True)
MANUAL_REPO_LIST = [
    "elastic/kibana",
    "prebid/Prebid.js",
    "danny-avila/LibreChat",
]

MANUAL_REPO_LIST = [
"apache/arrow",
"CleverRaven/Cataclysm-DDA",
"microsoft/ebpf-for-windows",
"envoyproxy/envoy",
"RobotLocomotion/drake",
"root-project/root",
"nasa/fprime",
"actor-framework/actor-framework",
"dragonflydb/dragonfly",
"scylladb/scylladb",
"qgis/QGIS",
]


# Get language-specific configurations
lang_config = get_language_config(TARGET_LANGUAGE)
PROJECT_ID = get_language_project_id(TARGET_LANGUAGE)
JSON_FOLDER = get_language_json_folder(TARGET_LANGUAGE)
CSV_FOLDER = get_language_csv_folder(TARGET_LANGUAGE)

# Global cache for LT data and spreadsheet data
LT_EXISTING_REPOS = None
SPREADSHEET_DATA = None
SPREADSHEET_ROW_INDICES = None
SPREADSHEET_ADDED_COL_INDEX = None

print(f"🔍 DEBUG: Directory setup:")
print(f"   JSON_FOLDER: {JSON_FOLDER}")
print(f"   CSV_FOLDER: {CSV_FOLDER}")
print(f"   JSON_FOLDER exists: {os.path.exists(JSON_FOLDER)}")
print(f"   CSV_FOLDER exists: {os.path.exists(CSV_FOLDER)}")

try:
    os.makedirs(JSON_FOLDER, exist_ok=True)
    print(f"✅ Created/verified JSON folder: {JSON_FOLDER}")
except Exception as e:
    print(f"❌ ERROR creating JSON folder {JSON_FOLDER}: {e}")

try:
    os.makedirs(CSV_FOLDER, exist_ok=True)
    print(f"✅ Created/verified CSV folder: {CSV_FOLDER}")
except Exception as e:
    print(f"❌ ERROR creating CSV folder {CSV_FOLDER}: {e}")


# ---------------------------------------------------------------------------
# Cache Management
# ---------------------------------------------------------------------------

def _clear_cache():
    """Clear the entire cache to ensure fresh data."""
    try:
        with FanoutCache("cache") as cache:
            cache.clear()
        print("🧹 Cache cleared successfully")
    except Exception as e:
        print(f"⚠️ Warning: Could not clear cache: {e}")

# ---------------------------------------------------------------------------
# Data Processing Helpers
# ---------------------------------------------------------------------------

def _construct_swe_url(instance_id: str) -> str:
    """Construct the SWE URL from instance ID.
    
    Args:
        instance_id: Instance ID (PR ID)
        
    Returns:
        Constructed SWE URL
    """
    return f"https://swe-bench-plus.turing.com/instances/{instance_id}"

def _make_api_request(method, url, **kwargs):
    """
    Centralized API request handler with error handling and retries.
    Exits gracefully on 401 Unauthorized errors with a clear message.
    """
    headers = kwargs.setdefault("headers", {})
    headers.update(_DEFAULT_HEADERS)
    
    # Determine which token is likely in use based on the URL
    hostname = urlparse(url).hostname
    token_name = "LT_TOKEN" if "eval.turing.com" in hostname else "SWE_TOKEN"

    for attempt in range(3):  # Retry up to 3 times
        try:
            res = requests.request(method, url, **kwargs)
            
            if res.status_code == 401:
                print(f"❌ FATAL: Received 401 Unauthorized for URL: {url}")
                print(f"   The '{token_name}' has likely expired or is invalid.")
                print(f"   Please update your token and try again.")
                sys.exit(1)
                
            res.raise_for_status()
            return res
            
        except requests.exceptions.RequestException as e:
            if attempt < 2:
                print(f"⚠️ Network error for {url}: {e}. Retrying in 5s...")
                time.sleep(5)
            else:
                print(f"❌ Failed to make request to {url} after 3 attempts: {e}")
                return None
    return None

def _process_pr_data(pr_rows: list, repo_name: str) -> list:
    """Process PR data to ensure all required fields are present.
    
    Args:
        pr_rows: Raw PR rows from webpage
        repo_name: Repository name
        
    Returns:
        Processed PR rows with all required fields
    """
    processed_rows = []
    
    for i, row in enumerate(pr_rows):
        if not isinstance(row, dict):
            continue
            
        # Create a copy to avoid modifying the original
        processed_row = row.copy()
        
        # Add repo field if not present
        if 'repo' not in processed_row:
            processed_row['repo'] = repo_name.replace('__', '/')
        
        # Try to find instance_id from various sources
        instance_id = None
        
        # First, check if instance_id is directly available
        if 'instance_id' in processed_row and processed_row['instance_id']:
            instance_id = str(processed_row['instance_id'])
        
        # Construct swe_url if missing
        if 'swe_url' not in processed_row or not processed_row['swe_url']:
            if instance_id:
                processed_row['swe_url'] = _construct_swe_url(instance_id)
        
        # Ensure pr_id is present
        if 'pr_id' not in processed_row or not processed_row['pr_id']:
            if instance_id:
                processed_row['pr_id'] = instance_id
        
        processed_rows.append(processed_row)
    
    return processed_rows

# ---------------------------------------------------------------------------
# SWE-Bench Helpers (unchanged logic, updated authentication)
# ---------------------------------------------------------------------------

_AUTH_COOKIES = {
    "auth_token": SWE_TOKEN,
    "eval_access_token": PERSONAL_LT_TOKEN,
}

_DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

def _get_repo_details(repo_name: str):
    """Return job info dict or None."""
    url = (
        "https://swe-bench-plus.turing.com/api/jobs/get?topic=get_relevant_prs&repo_id="
        + repo_name
    )
    res = _make_api_request("get", url, cookies=_AUTH_COOKIES)
    if not res:
        return None
    try:
        return res.json()
    except json.JSONDecodeError:
        return None

def _get_job_id(repo_name: str):
    info = _get_repo_details(repo_name)
    if not info:
        return None
    if info.get("status") in {"COMPLETED", "IN_PROGRESS", "NEW"}:
        return info.get("id")
    return None

def _start_job(repo_name: str) -> str | None:
    url = "https://swe-bench-plus.turing.com/api/jobs"
    payload = {
        "topic": "get_relevant_prs",
        "payload": {
            "repo_id": repo_name,
            "run_with_dockerfile": True,
            "repo": {
                "repo": repo_name,
                "repo_id": repo_name,
                "language": TARGET_LANGUAGE,
                "dockerfile": None,
                "updated_by_user_email": None,
            },
            "repo_name": repo_name,
            "min_test_files": 1,
            "max_non_test_files": 100,
            "max_prs": 1000,
        },
    }
    res = _make_api_request("post", url, json=payload, cookies=_AUTH_COOKIES)
    if not res or "application/json" not in res.headers.get("Content-Type", ""):
        print(f"❌ Failed to start job for {repo_name}: {res.text[:200] if res else 'No response'}")
        return None
    return res.json().get("jobId")

def _get_job_status(job_id: str) -> str:
    url = f"https://swe-bench-plus.turing.com/api/jobs/{job_id}"
    res = _make_api_request("get", url, cookies=_AUTH_COOKIES)
    if not res:
        return "FAILED"
    return res.json().get("status", "UNKNOWN")

def _get_pr_rows_via_web(repo_name: str, max_retries=3, retry_delay=10):
    """Scrape PR rows from the SWE-Bench repo page (JS renders JSON)."""
    print(f"🌐 Scraping webpage for {repo_name} PR data...")
    
    for attempt in range(max_retries):
        try:
            # Clear cache for this repo to ensure fresh data
            with FanoutCache("cache") as cache:
                cache.delete(f'{repo_name}_response')
            
            url = f'https://swe-bench-plus.turing.com/repos/{repo_name}'
            print(f"🔍 Attempt {attempt + 1}/{max_retries}: Fetching {url}")
            r = _make_api_request("get", url, cookies=_AUTH_COOKIES, headers={"Accept": "text/html"})
            print(f"🔍 Response status: {r.status_code if r else 'No Response'}")
            
            if not r:
                print(f"❌ Failed to fetch webpage for {repo_name}")
                if attempt < max_retries - 1:
                    print(f"⏳ Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"❌ Failed to fetch webpage after {max_retries} attempts")
                    return []
            
            response = r.text
            cache.set(f'{repo_name}_response', response)
            print(f"📁 Cached response for {repo_name}")
            
            print(f"🔍 Parsing HTML response...")
            soup = BeautifulSoup(response, "html.parser")
            
            # get the script with the id __NEXT_DATA__ 
            script = soup.find("script", id="__NEXT_DATA__")
            if script is None:
                print(f"❌ {repo_name} webpage doesn't contain expected __NEXT_DATA__ script")
                if attempt < max_retries - 1:
                    print(f"⏳ Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    return []
            
            try:
                data = json.loads(script.text)
                print(f"🔍 Successfully parsed JSON data")
                
                if isinstance(data, dict) and 'props' in data:
                    props = data['props']
                    
                    if isinstance(props, dict) and 'pageProps' in props:
                        page_props = props['pageProps']
                        
                        if isinstance(page_props, dict) and 'rows' in page_props:
                            rows = page_props['rows']
                            print(f"✅ Found {len(rows) if isinstance(rows, list) else 'non-list'} rows")
                            
                            if isinstance(rows, list) and rows:
                                return rows
                            else:
                                print(f"⚠️ No rows found in pageProps")
                                if attempt < max_retries - 1:
                                    print(f"⏳ Retrying in {retry_delay} seconds... (data might still be loading)")
                                    time.sleep(retry_delay)
                                    continue
                                else:
                                    print(f"❌ No rows found after {max_retries} attempts")
                                    return []
                        else:
                            print(f"⚠️ No 'rows' key found in pageProps")
                            if attempt < max_retries - 1:
                                print(f"⏳ Retrying in {retry_delay} seconds...")
                                time.sleep(retry_delay)
                                continue
                            else:
                                return []
                    else:
                        print(f"⚠️ No 'pageProps' key found in props")
                        if attempt < max_retries - 1:
                            print(f"⏳ Retrying in {retry_delay} seconds...")
                            time.sleep(retry_delay)
                            continue
                        else:
                            return []
                else:
                    print(f"⚠️ No 'props' key found in data")
                    if attempt < max_retries - 1:
                        print(f"⏳ Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        return []
                        
            except json.JSONDecodeError as e:
                print(f"❌ Error parsing JSON data for {repo_name}: {e}")
                if attempt < max_retries - 1:
                    print(f"⏳ Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    return []
            except Exception as e:
                print(f"❌ Unexpected error parsing data for {repo_name}: {e}")
                if attempt < max_retries - 1:
                    print(f"⏳ Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    return []
                    
        except requests.exceptions.RequestException as e:
            print(f"❌ Network error for {repo_name}: {e}")
            if attempt < max_retries - 1:
                print(f"⏳ Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                continue
            else:
                return []
    
    print(f"❌ Failed to get PR data for {repo_name} after {max_retries} attempts")
    return []

# ---------------------------------------------------------------------------
# LT Batch Creation
# ---------------------------------------------------------------------------

def _create_lt_batch(repo_name_safe: str, csv_path: str) -> str:
    """Upload CSV, create batch, return batch URL."""
    upload_url = "https://eval.turing.com/api/batches/upload/rlhf-metadata"
    create_url = "https://eval.turing.com/api/batches"
    import_url_tmpl = "https://eval.turing.com/api/batches/{}/import-rlhf"

    # 1. Upload file
    with open(csv_path, "rb") as f:
        up_res = _make_api_request(
            "post",
            upload_url,
            data={"project_type": "rlhf"},
            files={"file": f},
            headers={"Authorization": f"Bearer {PERSONAL_LT_TOKEN}"},
        )
    if not up_res:
        raise Exception("Failed to upload CSV to LT - no response received")
    file_link = up_res.json()["fileLink"]

    # 2. Create batch metadata
    batch_payload = {
        "name": repo_name_safe,
        "folder": file_link,
        "description": "",
        "status": "draft",
        "file": {},
        "isRLHFFolder": False,
        "shouldShowSubfolder": False,
        "isRLHFProjectSuite": True,
        "project": {
            "id": PROJECT_ID,
            "name": f"Swe-bench-{TARGET_LANGUAGE}",
            "status": "ongoing",
            "projectType": "rlhf",
            "readonly": False,
        },
        "projectId": PROJECT_ID,
        "projectType": "rlhf",
    }
    create_res = _make_api_request("post", create_url, json=batch_payload, headers={"Authorization": f"Bearer {PERSONAL_LT_TOKEN}"})
    if not create_res:
        raise Exception("Failed to create batch in LT - no response received")
    batch_id = create_res.json()["id"]

    # 3. Trigger import
    import_res = _make_api_request("post", import_url_tmpl.format(batch_id), json=batch_payload, headers={"Authorization": f"Bearer {PERSONAL_LT_TOKEN}"})
    if not import_res:
        raise Exception("Failed to trigger import in LT - no response received")

    return f"https://eval.turing.com/batches/{batch_id}/view"

# ---------------------------------------------------------------------------
# Spreadsheet Functions
# ---------------------------------------------------------------------------

def get_repos_from_sheet(sheet_name, creds_path, spreadsheet_key, target_count=10):
    """
    Fetches repositories from a Google Sheet efficiently by loading all data at once.
    """
    global SPREADSHEET_DATA, SPREADSHEET_ROW_INDICES, SPREADSHEET_ADDED_COL_INDEX
    
    print(f"🔍 Fetching repositories from sheet: {sheet_name}")
    
    try:
        # --- Authentication and Sheet Loading ---
        print("   🔐 Setting up authentication...")
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(creds_path, scopes=scope)
        client = gspread.authorize(creds)
        
        print("   📄 Opening spreadsheet...")
        spreadsheet = client.open_by_key(spreadsheet_key)
        sheet = spreadsheet.worksheet(sheet_name)
        
        # --- Efficient Data Fetching ---
        print("   📊 Fetching all sheet data at once...")
        all_data = sheet.get_all_values()
        
        if len(all_data) <= 1:
            print("   ❌ Sheet is empty or has only a header.")
            return []

        # --- DataFrame Processing ---
        header = all_data[0]
        df = pd.DataFrame(all_data[1:], columns=header)
        # Adjust index to match sheet row numbers (1-based index, plus header row)
        df.index = df.index + 2
        
        print(f"   📈 Loaded {len(df)} rows into DataFrame.")
        
        # --- Column and Data Validation ---
        required_columns = ['Repository', 'Good PRs > 2', 'Added', 'Relevant PRs count']
        for col in required_columns:
            if col not in df.columns:
                print(f"   ⚠️ Warning: Column '{col}' not found in sheet.")
                print(f"   Available columns: {list(df.columns)}")
                return []
        
        print("   ✅ All required columns found.")
        
        # --- Filtering and Sorting ---
        print("   🔍 Filtering repositories...")
        qualifying_df = df[(df['Good PRs > 2'] == 'Yes') & (df['Added'] == 'No')].copy()
        
        print(f"   📊 Found {len(qualifying_df)} qualifying repositories.")
        
        if qualifying_df.empty:
            return []

        # Convert 'Relevant PRs count' to numeric for sorting, handling errors
        qualifying_df['relevant_count_numeric'] = pd.to_numeric(
            qualifying_df['Relevant PRs count'], errors='coerce'
        ).fillna(0).astype(int)
        
        # Sort by relevance (descending)
        qualifying_df = qualifying_df.sort_values(by='relevant_count_numeric', ascending=False)
        
        # --- Cache Data for Updates ---
        all_repos = qualifying_df['Repository'].tolist()
        qualifying_row_indices = qualifying_df.index.tolist()
        
        # Cache the 'Added' column index (1-based) for later updates
        SPREADSHEET_ADDED_COL_INDEX = header.index('Added') + 1
        
        SPREADSHEET_DATA = {
            'repos': all_repos,
            'row_indices': qualifying_row_indices,
            'sheet': sheet
        }
        
        print(f"   ✅ Successfully processed {len(all_repos)} qualifying repositories.")
        
        # --- Display Top Repositories ---
        print("   📋 Top qualifying repositories:")
        top_n = min(10, len(all_repos))
        for i in range(top_n):
            repo_name = qualifying_df.iloc[i]['Repository']
            relevant_count = qualifying_df.iloc[i]['relevant_count_numeric']
            print(f"     {i+1}. {repo_name} (Relevant PRs: {relevant_count})")
        
        if len(all_repos) > top_n:
            print(f"     ... and {len(all_repos) - top_n} more")
        
        return all_repos
        
    except Exception as e:
        print(f"   ❌ Error fetching from Google Sheet: {e}")
        import traceback
        traceback.print_exc()
        return []

def update_spreadsheet_repo_status(sheet_name, repo_name, status="Yes"):
    """Update the 'Added' column for a repository in the Google Sheet using cached data."""
    global SPREADSHEET_DATA, SPREADSHEET_ADDED_COL_INDEX
    
    print(f"📝 Updating spreadsheet status for {repo_name} to '{status}'...")
    
    try:
        # Use cached data if available
        if SPREADSHEET_DATA is not None and SPREADSHEET_ADDED_COL_INDEX is not None:
            repos = SPREADSHEET_DATA['repos']
            row_indices = SPREADSHEET_DATA['row_indices']
            sheet = SPREADSHEET_DATA['sheet']
            
            # Find the index of the repository
            try:
                repo_index = repos.index(repo_name)
                row_index = row_indices[repo_index]
                
                # Update the cell directly using cached column index
                cell_address = f"{chr(64 + SPREADSHEET_ADDED_COL_INDEX)}{row_index}"
                sheet.update(cell_address, status)
                
                print(f"   ✅ Successfully updated {repo_name} status to '{status}' (row {row_index})")
                return True
                
            except ValueError:
                print(f"   ⚠️ Repository {repo_name} not found in cached data")
                return False
        
        # Fallback to original method if cache is not available
        print("   ⚠️ Using fallback method (cache not available)")
        creds_path = os.path.join(os.path.dirname(__file__), 'creds.json')
        spreadsheet_key = get_spreadsheet_key()
        
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(creds_path, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)
        
        # Get all data to find the row
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        # Find the row with matching repository name
        matching_rows = df[df['Repository'] == repo_name]
        
        if matching_rows.empty:
            print(f"   ⚠️ Repository {repo_name} not found in spreadsheet")
            return False
        
        # Get the row index (add 2 because sheet is 1-indexed and we have header)
        row_index = matching_rows.index[0] + 2
        
        # Find the 'Added' column index
        headers = sheet.row_values(1)
        added_col_index = None
        for i, header in enumerate(headers):
            if header == 'Added':
                added_col_index = i + 1  # Convert to 1-indexed
                break
        
        if added_col_index is None:
            print(f"   ❌ 'Added' column not found in spreadsheet")
            return False
        
        # Update the cell
        cell_address = f"{chr(64 + added_col_index)}{row_index}"  # Convert to A1 notation
        sheet.update(cell_address, status)
        
        print(f"   ✅ Successfully updated {repo_name} status to '{status}'")
        return True
        
    except Exception as e:
        print(f"   ❌ Error updating spreadsheet: {e}")
        return False

# ---------------------------------------------------------------------------
# Labeling Tool Integration
# ---------------------------------------------------------------------------

def get_existing_repos_from_lt(project_id):
    """Fetch all existing repository names from the labeling tool for a specific project."""
    global LT_EXISTING_REPOS
    
    # Return cached data if available
    if LT_EXISTING_REPOS is not None:
        print(f"🔍 Using cached LT data: {len(LT_EXISTING_REPOS)} existing repositories")
        return LT_EXISTING_REPOS
    
    print(f"🔍 Fetching existing repositories from labeling tool for project {project_id}...")
    
    headers = {"Authorization": f"Bearer {PERSONAL_LT_TOKEN}"}
    all_batches = []
    page = 1
    limit = 100
    
    # API URL for batches with project filter
    base_url = f"https://eval.turing.com/api/batches?sort%5B0%5D=createdAt%2CDESC&join%5B0%5D=batchStats&join%5B1%5D=importAttempts&filter%5B0%5D=projectId%7C%7C%24eq%7C%7C{project_id}"
    
    while True:
        paginated_url = f"{base_url}&limit={limit}&page={page}"
        print(f"   📄 Fetching batches from page {page}...")
        
        try:
            response = _make_api_request("get", paginated_url, headers=headers)
            if not response:
                break
            
            json_data = response.json()
            batches_on_page = json_data.get("data")
            
            if not batches_on_page:
                break
                
            all_batches.extend(batches_on_page)
            
            if len(batches_on_page) < limit:
                break
                
            page += 1
            
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Error fetching batches on page {page}: {e}")
            return set()
    
    # Extract repository names from batch names
    existing_repos = set()
    for batch in all_batches:
        batch_name = batch.get("name", "")
        if batch_name:
            existing_repos.add(batch_name)
            print(f"   📋 Found existing repo: {batch_name}")
    
    # Cache the result globally
    LT_EXISTING_REPOS = existing_repos
    
    print(f"   ✅ Found {len(existing_repos)} existing repositories in project {project_id}")
    return existing_repos

def initialize_lt_cache(project_id):
    """Initialize the LT cache by fetching all existing repositories once."""
    global LT_EXISTING_REPOS
    if LT_EXISTING_REPOS is None:
        LT_EXISTING_REPOS = get_existing_repos_from_lt(project_id)
    return LT_EXISTING_REPOS

def get_existing_pr_ids_for_repo(repo_name, project_id):
    """Fetch existing PR IDs for a specific repository from the labeling tool."""
    print(f"🔍 Fetching existing PR IDs for repo: {repo_name}")
    
    headers = {"Authorization": f"Bearer {PERSONAL_LT_TOKEN}"}
    existing_pr_ids = set()
    
    # First, find the batch for this repository
    base_url = f"https://eval.turing.com/api/batches?sort%5B0%5D=createdAt%2CDESC&join%5B0%5D=batchStats&join%5B1%5D=importAttempts&filter%5B0%5D=projectId%7C%7C%24eq%7C%7C{project_id}"
    
    try:
        response = _make_api_request("get", base_url, headers=headers)
        if not response:
            return existing_pr_ids
                
        json_data = response.json()
        batches = json_data.get("data", [])
        
        # Find batches that match the repo name (including part files)
        matching_batches = []
        for batch in batches:
            batch_name = batch.get("name", "")
            if batch_name.startswith(repo_name):
                matching_batches.append(batch)
                print(f"   📋 Found matching batch: {batch_name}")
        
        if not matching_batches:
            print(f"   ⚠️ No batches found for repo {repo_name}")
            return existing_pr_ids
        
        # Fetch conversations (PRs) for each matching batch
        for batch in matching_batches:
            batch_id = batch.get("id")
            if not batch_id:
                continue
                
            print(f"   📄 Fetching PRs from batch {batch_id} ({batch.get('name', 'Unknown')})...")
            
            # Fetch conversations for this batch
            conv_url = f"https://eval.turing.com/api/conversations?join%5B0%5D=project%7C%7Cid%2Cname&join%5B1%5D=batch%7C%7Cid%2Cname&join%5B2%5D=seed%7C%7Cmetadata&filter%5B0%5D=batchId%7C%7C%24in%7C%7C{batch_id}"
            
            conv_page = 1
            conv_limit = 100
            
            while True:
                paginated_conv_url = f"{conv_url}&limit={conv_limit}&page={conv_page}"
                
                try:
                    conv_response = _make_api_request("get", paginated_conv_url, headers=headers)
                    if not conv_response:
                        break
                        
                    conv_json_data = conv_response.json()
                    conversations = conv_json_data.get("data", [])
                    
                    if not conversations:
                        break
                    
                    # Extract PR IDs from conversations
                    for conv in conversations:
                        pr_id = conv.get("seed", {}).get("metadata", {}).get("pr_id")
                        if pr_id:
                            existing_pr_ids.add(str(pr_id))
                    
                    if len(conversations) < conv_limit:
                        break
                        
                    conv_page += 1
                    
                except requests.exceptions.RequestException as e:
                    print(f"   ❌ Error fetching conversations for batch {batch_id}: {e}")
                    break
        
        print(f"   ✅ Found {len(existing_pr_ids)} existing PR IDs for repo {repo_name}")
        
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Error fetching batches: {e}")
    
    return existing_pr_ids

def check_repo_exists_in_lt(repo_name, project_id):
    """Check if a repository exists in the labeling tool (including part files and __Public suffix)."""
    print(f"🔍 Checking if repo {repo_name} exists in labeling tool...")
    
    # Convert repo name to LT format (USER/REPO -> USER__REPO)
    lt_repo_name = repo_name.replace("/", "__")
    
    # Use cached existing repos from LT
    existing_repos = LT_EXISTING_REPOS
    if existing_repos is None:
        print(f"   ⚠️ LT cache not initialized, fetching data...")
        existing_repos = get_existing_repos_from_lt(project_id)
    
    # Check for exact match and part files, normalizing __Public suffix
    exact_match = lt_repo_name in existing_repos
    
    # Check for part files (e.g., USER__REPO_PART_002)
    part_files = [repo for repo in existing_repos if repo.startswith(lt_repo_name + "_PART_")]
    
    # Check for __Public suffix
    public_suffix_match = lt_repo_name + "__Public" in existing_repos
    
    if exact_match:
        print(f"   ✅ Found exact match: {lt_repo_name}")
        return True, lt_repo_name
    
    if part_files:
        print(f"   ✅ Found part files: {part_files}")
        return True, part_files[0]  # Return the first part file as reference
    
    if public_suffix_match:
        print(f"   ✅ Found __Public suffix match: {lt_repo_name}__Public")
        return True, lt_repo_name + "__Public"
    
    print(f"   ❌ Repository {repo_name} not found in labeling tool")
    return False, None

def compare_prs_and_skip_if_identical(repo_name, csv_path, project_id):
    """Compare PRs in CSV with existing PRs in LT and skip if identical."""
    print(f"🔍 Comparing PRs for {repo_name}...")
    
    # Get existing PR IDs from LT
    existing_pr_ids = get_existing_pr_ids_for_repo(repo_name, project_id)
    
    if not existing_pr_ids:
        print(f"   ✅ No existing PRs found in LT, proceeding with upload")
        return False  # Don't skip
    
    # Read PR IDs from CSV file
    csv_pr_ids = set()
    try:
        with open(csv_path, 'r', encoding='utf-8') as csv_file:
            reader = csv.reader(csv_file)
            next(reader)  # Skip header
            
            for row in reader:
                if row and len(row) > 0:
                    try:
                        metadata = json.loads(row[0])
                        pr_id = metadata.get("pr_id")
                        if pr_id:
                            csv_pr_ids.add(str(pr_id))
                    except (json.JSONDecodeError, KeyError):
                        continue
    except Exception as e:
        print(f"   ❌ Error reading CSV file: {e}")
        return False  # Don't skip on error
    
    print(f"   📊 CSV contains {len(csv_pr_ids)} PRs")
    print(f"   📊 LT contains {len(existing_pr_ids)} PRs")
    
    # Check if all CSV PRs already exist in LT
    new_prs = csv_pr_ids - existing_pr_ids
    if not new_prs:
        print(f"   ⚠️ All PRs in CSV already exist in LT, skipping upload")
        return True  # Skip upload
    
    print(f"   ✅ Found {len(new_prs)} new PRs to upload")
    return False  # Don't skip

# ---------------------------------------------------------------------------
# High-level repo processing
# ---------------------------------------------------------------------------

def _get_repo_stats_even_if_failed(repo: str, upload_mode: str = 'Good'):
    """Get repository statistics from PR reports even if SWE-Bench processing fails."""
    from convert import load_relevant_pr_ids_from_reports
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    try:
        all_report_pr_ids, relevant_pr_ids, good_pr_ids = load_relevant_pr_ids_from_reports(
            repo, base_dir, TARGET_LANGUAGE, upload_mode
        )
        
        # Create basic stats structure - all SWE-Bench counts are 0 since no data
        stats = {
            'initial_pr_count': 0,  # Will be 0 since no SWE-Bench data
            'after_date_filter_count': 0,
            'logical_pr_count': len(all_report_pr_ids),
            'good_pr_count': len(good_pr_ids),
            'final_pr_count': 0,
            'uploaded_pr_count': 0,
            'missing_pr_ids': list(good_pr_ids),  # All Good PRs are missing if no SWE-Bench data
            'success': False
        }
        
        print(f"📊 Report stats for {repo}:")
        print(f"   Total PRs in report: {len(all_report_pr_ids)}")
        print(f"   Relevant PRs: {len(relevant_pr_ids)}")
        print(f"   Good PRs: {len(good_pr_ids)}")
        print(f"   Missing PRs (no SWE-Bench data): {len(all_report_pr_ids)}")
        
        return stats
        
    except Exception as e:
        print(f"⚠️ Could not load PR report stats for {repo}: {e}")
        return {
            'initial_pr_count': 0,
            'after_date_filter_count': 0,
            'logical_pr_count': 0,
            'good_pr_count': 0,
            'final_pr_count': 0,
            'uploaded_pr_count': 0,
            'missing_pr_ids': [],
            'success': False
        }

def _process_single_repo(repo: str, upload_mode: str = 'Good'):
    repo_safe = repo.replace("/", "__")
    
    # Initialize tracking variables
    initial_pr_count = 0
    final_pr_count = 0
    uploaded_pr_count = 0
    error_message = ""

    # 1. Job handling
    job_id = _get_job_id(repo_safe) or _start_job(repo_safe)
    if not job_id:
        print(f"❌ Could not start job for {repo}")
        error_message = "Could not start SWE-Bench job"
        # Get stats from PR reports even if SWE-Bench fails
        repo_stats = _get_repo_stats_even_if_failed(repo, upload_mode)
        return {
            'status': 'failed',
            'initial_pr_count': initial_pr_count,
            'final_pr_count': final_pr_count,
            'uploaded_pr_count': uploaded_pr_count,
            'error_message': error_message,
            'pr_stats': repo_stats
        }

    # 2. Wait for completion
    while True:
        status = _get_job_status(job_id)
        print(f"⏳ {repo} – job {job_id} status: {status}")
        if status == "COMPLETED":
            break
        if status in {"FAILED", "CANCELLED"}:
            print(f"❌ Job failed for {repo}")
            error_message = f"SWE-Bench job failed with status: {status}"
            # Get stats from PR reports even if SWE-Bench fails
            repo_stats = _get_repo_stats_even_if_failed(repo, upload_mode)
            return {
                'status': 'failed',
                'initial_pr_count': initial_pr_count,
                'final_pr_count': final_pr_count,
                'uploaded_pr_count': uploaded_pr_count,
                'error_message': error_message,
                'pr_stats': repo_stats
            }
        time.sleep(10)

    # Add delay after job completion to ensure webpage data is loaded
    time.sleep(3)

    # 3. Scrape PR rows
    pr_rows = _get_pr_rows_via_web(repo_safe)
    if not pr_rows:
        print(f"❌ No PR data found for {repo}")
        error_message = "No PR data found in SWE-Bench"
        # Get stats from PR reports even if SWE-Bench fails
        repo_stats = _get_repo_stats_even_if_failed(repo, upload_mode)
        return {
            'status': 'failed',
            'initial_pr_count': initial_pr_count,
            'final_pr_count': final_pr_count,
            'uploaded_pr_count': uploaded_pr_count,
            'error_message': error_message,
            'pr_stats': repo_stats
        }
    
    # Track initial PR count
    initial_pr_count = len(pr_rows)

    # Process PR data to ensure all required fields are present
    print(f"🔧 Processing PR data to add missing fields...")
    processed_pr_rows = _process_pr_data(pr_rows, repo_safe)
    print(f"✅ Processed {len(processed_pr_rows)} PR rows")

    # 4. Save raw JSON
    json_path = os.path.abspath(os.path.join(JSON_FOLDER, f"{repo_safe}_pr_data.json"))
    for row in processed_pr_rows:
        row["repo"] = repo  # add repo field expected by convert
    try:
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(processed_pr_rows, jf, indent=2)
        print(f"💾 Saved JSON ⇒ {json_path} ({len(processed_pr_rows)} PRs)")
        
    except Exception as e:
        print(f"❌ ERROR: Failed to save JSON file {json_path}: {e}")
        error_message = f"Failed to save JSON file: {e}"
        # Get stats from PR reports even if JSON save fails
        repo_stats = _get_repo_stats_even_if_failed(repo, upload_mode)
        return {
            'status': 'failed',
            'initial_pr_count': initial_pr_count,
            'final_pr_count': final_pr_count,
            'uploaded_pr_count': uploaded_pr_count,
            'error_message': error_message,
            'pr_stats': repo_stats
        }

    # 5. Convert to CSV using updated signature
    csv_path = os.path.abspath(os.path.join(CSV_FOLDER, f"{repo_safe}_pr_data.csv"))
    
    try:
        result = process_json_file(
            input_file=json_path,
            output_file=csv_path,
            existing_repos=set(),
            force=False,
            base_dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            language=TARGET_LANGUAGE,
            upload_mode=upload_mode,
        )
        print(f"✅ process_json_file completed successfully")
        
        # This check is crucial to handle both old and new return types
        if not isinstance(result, dict) or not result.get('success'):
             error_message = f"process_json_file returned an unexpected value or failed: {result}"
             print(f"❌ {error_message}")
             return {
                'status': 'failed',
                'initial_pr_count': initial_pr_count,
                'final_pr_count': 0,
                'uploaded_pr_count': 0,
                'error_message': error_message,
                'pr_stats': {}
             }

        print(f"📊 Result: {json.dumps(result, indent=2)}")
        final_pr_count = result.get('final_pr_count', 0)
        
        # Always save CSV if there are usable PRs
        if final_pr_count > 0:
             print(f"💾 Saved CSV file with {final_pr_count} PRs to {csv_path}")

        if final_pr_count == 0:
            print(f"⚠️ No usable PRs found for {repo} after filtering.")
            return {
                'status': 'no_prs',
                'initial_pr_count': initial_pr_count,
                'final_pr_count': 0,
                'uploaded_pr_count': 0,
                'error_message': "No usable PRs after filtering",
                'pr_stats': result  # Pass stats even for no_prs
            }

    except Exception as e:
        print(f"❌ ERROR in process_json_file: {e}")
        import traceback
        traceback.print_exc()
        error_message = f"Error in process_json_file: {e}"
        return {
            'status': 'failed',
            'initial_pr_count': initial_pr_count,
            'final_pr_count': 0,
            'uploaded_pr_count': 0,
            'error_message': error_message,
            'pr_stats': {} # Return empty stats on failure
        }
    
    # 6. Check if repository already exists in LT and compare PRs
    exists_in_lt, existing_repo_name = check_repo_exists_in_lt(repo, PROJECT_ID)
    
    if exists_in_lt:
        print(f"🔍 Repository {repo} exists in LT as {existing_repo_name}")
        
        # Compare PRs to see if we should skip
        should_skip = compare_prs_and_skip_if_identical(repo, csv_path, PROJECT_ID)
        
        if should_skip:
            print(f"⏭️ Skipping upload for {repo} - all PRs already exist in LT")
            # Update spreadsheet to mark as added
            sheet_name = get_language_sheet_name(TARGET_LANGUAGE)
            update_spreadsheet_repo_status(sheet_name, repo, "Yes")
            return {
                'status': 'skipped',
                'initial_pr_count': initial_pr_count,
                'final_pr_count': final_pr_count,
                'uploaded_pr_count': uploaded_pr_count,
                'error_message': "All PRs already exist in labeling tool",
                'pr_stats': result  # Pass the full stats dictionary
            }
        else:
            print(f"✅ Proceeding with upload for {repo} - new PRs found")

    # 7. Upload to LT
    try:
        batch_url = _create_lt_batch(repo_safe, csv_path)
        print(f"✅ Batch created: {batch_url}")
        
        # Track uploaded PR count
        uploaded_pr_count = final_pr_count
        
        # 8. Update spreadsheet to mark as added
        sheet_name = get_language_sheet_name(TARGET_LANGUAGE)
        update_spreadsheet_repo_status(sheet_name, repo, "Yes")
        print(f"📝 Updated spreadsheet status for {repo}")
        print()
        
        return {
            'status': 'success',
            'initial_pr_count': initial_pr_count,
            'final_pr_count': final_pr_count,
            'uploaded_pr_count': uploaded_pr_count,
            'error_message': "",
            'pr_stats': result  # Pass the full stats dictionary
        }
        
    except Exception as e:
        print(f"❌ Failed to create LT batch for {repo}: {e}")
        error_message = f"Failed to create labeling tool batch: {e}"
        return {
            'status': 'failed',
            'initial_pr_count': initial_pr_count,
            'final_pr_count': final_pr_count,
            'uploaded_pr_count': 0,  # No PRs uploaded due to failure
            'error_message': error_message,
            'pr_stats': result  # Pass the stats even on failure
        }

# ---------------------------------------------------------------------------
# Processing Report Functions
# ---------------------------------------------------------------------------

def create_processing_report(processing_stats, base_dir):
    """Create a comprehensive CSV report of processing statistics for batch creation."""
    if not processing_stats:
        return
    
    # Create processing_reports directory if it doesn't exist
    reports_dir = os.path.join(base_dir, "processing_reports")
    os.makedirs(reports_dir, exist_ok=True)
    
    # Generate ISO timestamp for filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"batch_processing_report_{timestamp}.csv"
    report_path = os.path.join(reports_dir, report_filename)
    
    # Calculate summary statistics
    total_repos = len(processing_stats)
    successful_repos = sum(1 for stat in processing_stats if stat.get('status') == 'success')
    failed_repos = sum(1 for stat in processing_stats if stat.get('status') == 'failed')
    skipped_repos = sum(1 for stat in processing_stats if stat.get('status') == 'skipped')
    no_prs_repos = sum(1 for stat in processing_stats if stat.get('status') == 'no_prs')
    
    # Calculate PR statistics
    total_initial_prs = sum(stat.get('initial_pr_count', 0) for stat in processing_stats)
    total_final_prs = sum(stat.get('final_pr_count', 0) for stat in processing_stats)
    total_uploaded_prs = sum(stat.get('uploaded_pr_count', 0) for stat in processing_stats)
    
    # Count repositories with no usable PRs
    repos_with_no_prs = sum(1 for stat in processing_stats if stat.get('final_pr_count', 0) == 0)
    
    # New detailed totals
    total_pr_total = sum(stat.get('pr_total', 0) for stat in processing_stats)
    total_prs_after_merge_date = sum(stat.get('prs_after_merge_date', 0) for stat in processing_stats)
    total_prs_logical = sum(stat.get('prs_logical', 0) for stat in processing_stats)
    total_prs_good = sum(stat.get('prs_good', 0) for stat in processing_stats)
    total_prs_uploaded_detail = sum(stat.get('prs_uploaded', 0) for stat in processing_stats)
    total_prs_missing = sum(stat.get('prs_missing', 0) for stat in processing_stats)
    
    # Write the report
    with open(report_path, 'w', newline='', encoding='utf-8') as csv_file:
        writer = csv.writer(csv_file)
        
        # Write summary header
        writer.writerow(['BATCH PROCESSING SUMMARY REPORT'])
        writer.writerow([f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'])
        writer.writerow([f'Target Language: {TARGET_LANGUAGE}'])
        writer.writerow([f'Project ID: {PROJECT_ID}'])
        writer.writerow([f'Upload Mode: {UPLOAD_MODE}'])
        writer.writerow([f'Total Repositories Processed: {total_repos}'])
        writer.writerow([f'Successful Uploads: {successful_repos}'])
        writer.writerow([f'Failed: {failed_repos}'])
        writer.writerow([f'Skipped (already in LT): {skipped_repos}'])
        writer.writerow([f'Skipped (no usable PRs): {no_prs_repos}'])
        writer.writerow([f'Repositories with No Usable PRs: {repos_with_no_prs}'])
        writer.writerow([])
        
        # Write totals
        writer.writerow(['TOTALS ACROSS ALL REPOSITORIES'])
        writer.writerow(['PR Total', 'PRs After Merge Date', 'PRs Logical', 'PRs Good', 'PRs Uploaded', 'PRs Missing'])
        writer.writerow([total_pr_total, total_prs_after_merge_date, total_prs_logical, total_prs_good, total_prs_uploaded_detail, total_prs_missing])
        writer.writerow([])
        
        # Write detailed repository data
        writer.writerow(['DETAILED REPOSITORY STATISTICS'])
        writer.writerow(['Repository', 'Status', 
                       'PR Total', 'PRs After Merge Date', 'PRs Logical', 'PRs Good', 
                       'PRs Uploaded', 'PRs Missing', 'PRs Missing IDs', 
                       'Error Message'])
        
        for stat in processing_stats:
            writer.writerow([
                stat.get('repository', 'Unknown'),
                stat.get('status', 'Unknown'),
                stat.get('pr_total', 0),
                stat.get('prs_after_merge_date', 0),
                stat.get('prs_logical', 0),
                stat.get('prs_good', 0),
                stat.get('prs_uploaded', 0),
                stat.get('prs_missing', 0),
                stat.get('prs_missing_ids', ''),
                stat.get('error_message', '')
            ])
    
    print(f"\n📊 Batch processing report saved to: {report_path}")
    print(f"📈 Summary: {successful_repos}/{total_repos} repositories processed successfully")
    print(f"📊 Total PRs: {total_initial_prs} → {total_final_prs} (final) → {total_uploaded_prs} (uploaded)")
    print(f"⚠️ Repositories with no usable PRs: {repos_with_no_prs}")
    
    return report_path

def track_repo_processing_stats(repo_name, status, initial_pr_count=0, final_pr_count=0, uploaded_pr_count=0, error_message="", pr_stats=None):
    """Track processing statistics for a single repository, including detailed PR counts."""
    
    # Initialize base stats
    stats = {
        'repository': repo_name,
        'status': status,
        'initial_pr_count': initial_pr_count,
        'final_pr_count': final_pr_count,
        'uploaded_pr_count': uploaded_pr_count,
        'error_message': error_message,
        # New detailed stats
        'pr_total': 0,
        'prs_after_merge_date': 0,
        'prs_logical': 0,
        'prs_good': 0,
        'prs_uploaded': 0,
        'prs_missing': 0,
        'prs_missing_ids': ""
    }
    
    # If detailed stats are provided, update the dictionary
    if pr_stats and isinstance(pr_stats, dict):
        stats.update({
            'pr_total': pr_stats.get('initial_pr_count', 0),
            'prs_after_merge_date': pr_stats.get('after_date_filter_count', 0),
            'prs_logical': pr_stats.get('logical_pr_count', 0),
            'prs_good': pr_stats.get('good_pr_count', 0),
            'prs_uploaded': pr_stats.get('final_pr_count', 0),
            'prs_missing': len(pr_stats.get('missing_pr_ids', [])),
            'prs_missing_ids': ", ".join(map(str, pr_stats.get('missing_pr_ids', [])))
        })
        # Ensure consistency
        stats['initial_pr_count'] = pr_stats.get('initial_pr_count', initial_pr_count)
        stats['final_pr_count'] = pr_stats.get('final_pr_count', final_pr_count)
        stats['uploaded_pr_count'] = pr_stats.get('uploaded_pr_count', uploaded_pr_count)

    return stats

# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def main():
    print("=== SWE-Bench Batch Creator V2 ===")
    print(f"Target language : {TARGET_LANGUAGE}")
    print(f"Project ID      : {PROJECT_ID}")
    print(f"Upload mode     : {UPLOAD_MODE}")
    print(f"Target repos    : {TARGET_REPO_COUNT}")
    print(f"Repos source    : {'Manual list' if USE_MANUAL_REPOS else 'Google Sheet'}")
    print("=" * 50)

    # Clear cache to ensure fresh data
    _clear_cache()

    # Initialize LT cache once at the beginning
    print("🔍 Initializing labeling tool cache...")
    initialize_lt_cache(PROJECT_ID)

    # Get repository list
    repo_list = []
    if USE_MANUAL_REPOS:
        repo_list = MANUAL_REPO_LIST
        print(f"📋 Using manual repository list: {len(repo_list)} repos")
        print(f"   {repo_list}")
    else:
        # Get repositories from Google Sheet
        creds_path = os.path.join(os.path.dirname(__file__), 'creds.json')
        spreadsheet_key = get_spreadsheet_key()
        sheet_name = get_language_sheet_name(TARGET_LANGUAGE)
        repo_list = get_repos_from_sheet(sheet_name, creds_path, spreadsheet_key, TARGET_REPO_COUNT)
        
        if not repo_list:
            print("❌ No qualifying repositories found in Google Sheet.")
            return

    print(f"\n🚀 Starting processing...")
    print(f"   Target: {TARGET_REPO_COUNT} repositories")
    print(f"   Available: {len(repo_list)} repositories")
    print(f"   Stopping criteria: Reach target OR exhaust all repos")
    print("-" * 50)

    # Process repositories
    successful_count = 0
    failed_count = 0
    skipped_count = 0
    no_prs_count = 0
    processing_stats = []  # Track detailed statistics
    
    for i, repo in enumerate(repo_list, 1):
        print(f"\n--- Processing {i}/{len(repo_list)}: {repo} ---")
        print(f"   Progress: {successful_count}/{TARGET_REPO_COUNT} successful uploads")
        
        try:
            # Check if repository already exists in the labeling tool
            exists_in_lt, existing_repo_name = check_repo_exists_in_lt(repo, PROJECT_ID)
            
            if exists_in_lt:
                print(f"⚠️ Repository {repo} already exists in labeling tool as {existing_repo_name}. Skipping.")
                # Update spreadsheet to mark as added
                sheet_name = get_language_sheet_name(TARGET_LANGUAGE)
                update_spreadsheet_repo_status(sheet_name, repo, "Yes")
                skipped_count += 1
                print(f"   Skipped count: {skipped_count}")
                
                # Get stats from PR reports even for skipped repos
                repo_stats = _get_repo_stats_even_if_failed(repo, UPLOAD_MODE)
                processing_stats.append(track_repo_processing_stats(
                    repo, 'skipped', 0, 0, 0, "Repository already exists in labeling tool", pr_stats=repo_stats
                ))
                continue

            result = _process_single_repo(repo, UPLOAD_MODE)
            
            # Track statistics using the helper function to flatten the data
            stats_entry = track_repo_processing_stats(
                repo_name=repo,
                status=result['status'],
                initial_pr_count=result.get('initial_pr_count', 0),
                final_pr_count=result.get('final_pr_count', 0),
                uploaded_pr_count=result.get('uploaded_pr_count', 0),
                error_message=result.get('error_message', ""),
                pr_stats=result.get('pr_stats')
            )
            processing_stats.append(stats_entry)
            
            if result['status'] == "success":
                successful_count += 1
                print(f"✅ Successfully processed {repo} ({successful_count}/{TARGET_REPO_COUNT})")
                
                if successful_count >= TARGET_REPO_COUNT:
                    print(f"🎯 Reached target count of {TARGET_REPO_COUNT}. Stopping.")
                    break
            elif result['status'] == "no_prs":
                print(f"⚠️ No usable PRs found for {repo}. Skipping upload.")
                no_prs_count += 1
                print(f"   No PRs count: {no_prs_count}")
            elif result['status'] == "skipped":
                print(f"⏭️ Skipped {repo} - all PRs already exist in LT")
                skipped_count += 1
                print(f"   Skipped count: {skipped_count}")
            else:  # status == "failed"
                failed_count += 1
                print(f"❌ Failed to process {repo}")
                print(f"   Failed count: {failed_count}")
                
        except Exception as exc:
            failed_count += 1
            print(f"❌ Unexpected error processing {repo}: {exc}")
            print(f"   Failed count: {failed_count}")
            
            # Get stats from PR reports even for unexpected errors
            repo_stats = _get_repo_stats_even_if_failed(repo, UPLOAD_MODE)
            processing_stats.append(track_repo_processing_stats(
                repo, 'failed', 0, 0, 0, f"Unexpected error: {exc}", pr_stats=repo_stats
            ))

    # Final summary
    print("\n" + "=" * 50)
    print("📊 FINAL SUMMARY")
    print("=" * 50)
    print(f"Target repositories: {TARGET_REPO_COUNT}")
    print(f"Available repositories: {len(repo_list)}")
    print(f"Successfully processed: {successful_count}")
    print(f"Skipped (already in LT): {skipped_count}")
    print(f"Skipped (no usable PRs): {no_prs_count}")
    print(f"Failed to process: {failed_count}")
    print(f"Remaining in queue: {len(repo_list) - (successful_count + failed_count + skipped_count + no_prs_count)}")
    
    if successful_count >= TARGET_REPO_COUNT:
        print(f"🎉 SUCCESS: Reached target of {TARGET_REPO_COUNT} repositories!")
    elif successful_count + failed_count + skipped_count + no_prs_count >= len(repo_list):
        print(f"⚠️ EXHAUSTED: Processed all {len(repo_list)} available repositories.")
        print(f"   Only {successful_count} were successfully uploaded (target was {TARGET_REPO_COUNT})")
        print(f"   {skipped_count} were skipped (already in labeling tool)")
        print(f"   {no_prs_count} were skipped (no usable PRs)")
    else:
        print(f"⏸️ STOPPED: Processing interrupted or stopped early.")
    
    print("=" * 50)
    
    # Generate processing report
    if processing_stats:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Root directory (parent of src)
        create_processing_report(processing_stats, base_dir)

if __name__ == "__main__":
    main() 
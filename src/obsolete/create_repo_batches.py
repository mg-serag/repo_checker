"""
Repository Batch Creation Script

This script creates LT batches from repositories based on language configuration.

Usage Options:
1. Direct execution (modify TARGET_LANGUAGE in configuration section):
   python create_repo_batches.py

2. Command line with target language:
   python create_repo_batches.py JavaScript

3. Command line with manual repository list:
   python create_repo_batches.py JavaScript --manual user/repo1 user/repo2

4. Command line with custom count:
   python create_repo_batches.py JavaScript --count 20
"""

import json
import os
import requests
import time
from diskcache import FanoutCache
from bs4 import BeautifulSoup
import argparse
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from config_utils import get_language_config, get_language_sheet_name, get_language_project_id, get_language_json_folder, get_language_csv_folder, get_swe_token, get_lt_token

# Import convert.py functions for proper processing
from convert import convert_folder, process_directory, fetch_existing_repos_for_project, process_json_file

# Load tokens from config.json using config_utils for centralized configuration management
PERSONAL_LT_TOKEN = get_lt_token()
SWE_TOKEN = get_swe_token()

# --- Script Configuration ---
# Set your target language here to run the script directly without command line arguments
TARGET_LANGUAGE = 'JavaScript'  # Options: 'Java', 'JavaScript', 'Python', 'Go', 'C/C++', 'Rust', 'C#', 'Ruby'
DEFAULT_COUNT = 3  # Number of repositories to fetch from sheet
USE_MANUAL_REPOS = False  # Set to True to use MANUAL_REPO_LIST instead of sheet

# Upload filtering mode - controls which PRs to include in the final CSV
# All: Upload all PRs found in the JSON file (only do deduplication step to remove PRs already in SWE Bench)
# Good: Filter to include only Good PRs (PRs marked as "Good PR" in the PR reports)
# Logical: Filter to include all PRs in the PR report whether the agent judged them as good or bad
UPLOAD_MODE = 'Good'  # Options: 'All', 'Good', 'Logical'

# Manual repository list (only used if USE_MANUAL_REPOS = True)
MANUAL_REPO_LIST = [
    # "user/repo1",
    # "user/repo2",
]

# Helper: Build authentication cookies & headers for SWE Bench / LT requests

def _get_auth_cookies() -> dict:
    """Return a cookies dict required by SWE-Bench endpoints."""
    if not SWE_TOKEN or not PERSONAL_LT_TOKEN:
        raise ValueError("SWE_TOKEN or PERSONAL_LT_TOKEN is not configured. Please check config.json")
    return {
        "auth_token": SWE_TOKEN,
        "eval_access_token": PERSONAL_LT_TOKEN
    }


def _get_default_headers() -> dict:
    """Common JSON headers."""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def get_repo_details(repo_name):
    """Get repository job details from SWE Bench Plus API."""
    url = f"https://swe-bench-plus.turing.com/api/jobs/get?topic=get_relevant_prs&repo_id={repo_name}"
    print(f"🔍 Calling: {url}")
    
    try:
        response = requests.get(
            url,
            cookies=_get_auth_cookies(),
            headers=_get_default_headers()
        )
        
        print(f"🔍 Response status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ Error getting repo details: HTTP {response.status_code}")
            print(f"❌ Response text: {response.text}")
            return None
        
        result = response.json()
        return result
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error getting repo details for {repo_name}: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing repo details response for {repo_name}: {e}")
        print(f"❌ Raw response: {response.text}")
        return None

def get_job_id(repo_name):
    """Get existing job ID for a repository, if any."""
    try:
        response = get_repo_details(repo_name)
        statuses = ["COMPLETED", "IN_PROGRESS", "NEW"]
        if response and isinstance(response, dict):
            status = response.get("status")
            job_id = response.get('id')
            print(f"🔍 Found job {job_id} with status '{status}' for {repo_name}")
            return job_id if status in statuses else None
        else:
            print(f"🔍 No existing job found for {repo_name}")
            return None
    except Exception as e:
        print(f"❌ Error checking repo {repo_name}: {e}")
        return None

def start_job(repo_name, target_language="TypeScript"):
    """Start a new job for processing a repository in SWE Bench Plus."""
    url = f"https://swe-bench-plus.turing.com/api/jobs"
    data = {
        "topic": "get_relevant_prs",
        "payload": {
            "repo_id": repo_name,
            "run_with_dockerfile": True,
            "repo": {
                "repo": repo_name,
                "repo_id": repo_name,
                "language": target_language,
                "dockerfile": None,
                "updated_by_user_email": None
            },
            "repo_name": repo_name,
            "min_test_files": 1,
            "max_non_test_files": 100,
            "max_prs": 1000
            },
    }
    print(f"📝 Starting job with payload:")
    print(f"   URL: {url}")
    print(f"   Topic: {data['topic']}")
    print(f"   Repo ID: {repo_name}")
    print(f"   Language: {target_language}")
    print(f"   Full payload: {json.dumps(data, indent=2)}")
    
    response = requests.post(
        url,
        cookies=_get_auth_cookies(),
        headers=_get_default_headers(),
        json=data
    )
    
    print(f"📝 Start job response status: {response.status_code}")
    
    # Validate response is JSON
    if 'application/json' not in response.headers.get('Content-Type', ''):
        print("❌ Unexpected response content-type – likely authentication failure.")
        print("❌ Response preview (first 200 chars):")
        print(response.text[:200])
        return None
    
    if response.status_code != 200:
        print(f"❌ Error starting job: HTTP {response.status_code}")
        print(f"❌ Response text: {response.text}")
        return None
        
    try:
        result = response.json()
        job_id = result.get("jobId")
        if job_id:
            print(f"✅ Successfully started job {job_id} for {repo_name}")
            return job_id
        else:
            print(f"❌ No jobId in response: {result}")
            return None
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing start job response: {e}")
        print(f"Response text: {response.text}")
        return None

def get_job_status(job_id):
    """Get the current status of a job."""
    url = f"https://swe-bench-plus.turing.com/api/jobs/{job_id}"
    try:
        response = requests.get(
            url,
            cookies=_get_auth_cookies(),
            headers=_get_default_headers()
        )
        
        if response.status_code != 200:
            print(f"❌ Error getting job status: HTTP {response.status_code} - {response.text}")
            return "FAILED"
            
        result = response.json()
        status = result.get("status", "UNKNOWN")
        return status
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error getting job status for {job_id}: {e}")
        return "FAILED"
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing job status response for {job_id}: {e}")
        return "FAILED"


def add_repo_simple(repo_name, target_language="JavaScript", max_retries=3, retry_delay=10):
    """
    Simplified version matching the original working script exactly.
    Returns PR list directly, handles job management internally.
    """
    print(f"🔍 Starting add_repo_simple for {repo_name}")
    
    # Use the improved working method
    return get_pr_list_via_working_method(repo_name, target_language, max_retries, retry_delay)

def get_pr_list_via_working_method(repo, target_language="JavaScript", max_retries=3, retry_delay=10):
    """
    Get PR list using the proven working method from the original script:
    
    1. Start or get existing job
    2. Wait for completion (simple while loop, no timeout)
    3. Scrape the webpage to get PR data (not API response)
    """
    print(f"🔍 Processing repo {repo} using proven SWE Bench workflow...")
    
    # Step 1: Get or start job (same as original)
    try:
        job_id = get_job_id(repo)
        if not job_id:
            print(f"📝 Starting new job for {repo}...")
            job_id = start_job(repo, target_language)
            if not job_id:
                print(f"❌ Failed to start job for {repo}")
                return []
        else:
            print(f"📋 Found existing job {job_id} for {repo}")
    except Exception as e:
        print(f"❌ Error with job management for {repo}: {e}")
        return []
    
    # Step 2: Wait for completion (same as original - simple while loop)
    print(f"⏳ Waiting for job {job_id} to complete...")
    try:
        while get_job_status(job_id) != "COMPLETED":
            time.sleep(10)
            status = get_job_status(job_id)
            print(f"⏳ Job {job_id} status: {status}")
            if status in ["FAILED", "CANCELLED"]:
                print(f"❌ Job {job_id} failed with status: {status}")
                return []
        print(f"✅ {repo} job completed!")
    except Exception as e:
        print(f"❌ Error waiting for job completion: {e}")
        return []
    
    # Add delay after job completion to ensure webpage data is loaded
    print(f"⏳ Waiting 3 seconds for webpage data to load...")
    time.sleep(3)
    
    # Step 3: Get PR list via webpage scraping (same as original)
    try:
        print(f"🌐 Scraping webpage for {repo} PR data...")
        pr_list = get_pr_list_from_webpage(repo, max_retries, retry_delay)
        if pr_list:
            print(f"✅ Retrieved {len(pr_list)} PRs via webpage scraping")
            
            # Process PR data to ensure all required fields are present
            print(f"🔧 Processing PR data to add missing fields...")
            processed_pr_list = _process_pr_data(pr_list, repo)
            print(f"✅ Processed {len(processed_pr_list)} PR rows")
            
            return processed_pr_list
        else:
            print(f"❌ No PRs found via webpage scraping for {repo}")
            return []
    except Exception as e:
        print(f"❌ Error scraping webpage for {repo}: {e}")
        import traceback
        traceback.print_exc()
        return []

def get_pr_list_from_webpage(repo, max_retries=3, retry_delay=10):
    """
    Get PR list by scraping the SWE Bench Plus webpage with retry logic.
    
    Args:
        repo: Repository name
        max_retries: Maximum number of retry attempts
        retry_delay: Delay in seconds between retries
    """
    print(f"🌐 Scraping webpage for {repo} PR data...")
    
    for attempt in range(max_retries):
        try:
            # Clear cache for this repo to ensure fresh data
            with FanoutCache("cache") as cache:
                cache.delete(f'{repo}_response')
            
            url = f'https://swe-bench-plus.turing.com/repos/{repo}'
            print(f"🔍 Attempt {attempt + 1}/{max_retries}: Fetching {url}")
            
            response = requests.get(
                url,
                cookies=_get_auth_cookies(),
                headers={"Accept": "text/html"},
                timeout=30  # Add timeout
            )
            
            if response.status_code != 200:
                print(f"❌ HTTP {response.status_code} for {repo}")
                if attempt < max_retries - 1:
                    print(f"⏳ Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"❌ Failed to fetch webpage after {max_retries} attempts")
                    return []
            
            # Parse the response
            soup = BeautifulSoup(response.text, "html.parser")
            script = soup.find("script", id="__NEXT_DATA__")
            
            if script is None:
                print(f"❌ {repo} webpage doesn't contain expected __NEXT_DATA__ script")
                if attempt < max_retries - 1:
                    print(f"⏳ Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    return []
            
            try:
                data = json.loads(script.text)
                rows = data.get("props", {}).get("pageProps", {}).get("rows", [])
                
                if not rows:
                    print(f"⚠️ No rows found in webpage data for {repo}")
                    if attempt < max_retries - 1:
                        print(f"⏳ Retrying in {retry_delay} seconds... (data might still be loading)")
                        time.sleep(retry_delay)
                        continue
                    else:
                        print(f"❌ No rows found after {max_retries} attempts")
                        return []
                
                print(f"✅ Successfully found {len(rows)} PRs for {repo}")
                return rows
                
            except (json.JSONDecodeError, KeyError) as e:
                print(f"❌ Error parsing webpage data for {repo}: {e}")
                if attempt < max_retries - 1:
                    print(f"⏳ Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    return []
                    
        except requests.exceptions.RequestException as e:
            print(f"❌ Network error for {repo}: {e}")
            if attempt < max_retries - 1:
                print(f"⏳ Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                continue
            else:
                return []
    
    print(f"❌ Failed to get PR data for {repo} after {max_retries} attempts")
    return []


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
    Returns all qualifying repositories sorted by relevance.
    """
    print(f"Fetching repositories from sheet: {sheet_name}")
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(creds_path, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)
        
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        print(f"Total repositories in sheet: {len(df)}")
        print(f"Columns in sheet: {df.columns.tolist()}")
        
        # Debug: Check current values
        print(f"Good PRs > 2 values: {df['Good PRs > 2'].unique()}")
        print(f"Added values: {df['Added'].unique()}")
        
        # Filter based on criteria - STRICT filtering
        criteria_df = df[(df['Good PRs > 2'] == 'Yes') & (df['Added'] == 'No')]
        print(f"Repositories meeting criteria (Good PRs > 2 = Yes AND Added = No): {len(criteria_df)}")
        
        if len(criteria_df) == 0:
            print("❌ No repositories found matching criteria!")
            print("Available repositories with Good PRs > 2 = Yes:")
            good_prs_df = df[df['Good PRs > 2'] == 'Yes']
            for idx, row in good_prs_df.iterrows():
                print(f"  - {row['Repository']}: Added = {row['Added']}")
            return []
        
        # Sort by 'Relevant PRs count'
        sorted_df = criteria_df.sort_values(by='Relevant PRs count', ascending=False)
        
        # Return all qualifying repositories (not just the top N)
        all_repos = sorted_df['Repository'].tolist()
        print(f"✅ Found {len(all_repos)} qualifying repositories, target count: {count}")
        for i, repo in enumerate(all_repos, 1):
            repo_row = sorted_df[sorted_df['Repository'] == repo].iloc[0]
            print(f"  {i}. {repo} (Relevant PRs: {repo_row['Relevant PRs count']}, Added: {repo_row['Added']})")
        
        return all_repos
        
    except Exception as e:
        print(f"Error fetching from Google Sheet: {e}")
        import traceback
        traceback.print_exc()
        return []

def clear_cache():
    """Clear the entire cache to ensure fresh data."""
    try:
        with FanoutCache("cache") as cache:
            cache.clear()
        print("🧹 Cache cleared successfully")
    except Exception as e:
        print(f"⚠️ Warning: Could not clear cache: {e}")

def _construct_swe_url(instance_id: str) -> str:
    """Construct the SWE URL from instance ID.
    
    Args:
        instance_id: Instance ID (PR ID)
        
    Returns:
        Constructed SWE URL
    """
    return f"https://swe-bench-plus.turing.com/instances/{instance_id}"

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

def display_progress(processed_repos, total_repos, uploaded_batches, target_count):
    """Display current progress information."""
    print(f"\n{'='*60}")
    print(f"📊 PROGRESS UPDATE")
    print(f"{'='*60}")
    print(f"📋 Total repositories to process: {total_repos}")
    print(f"🔄 Currently processing: {processed_repos}/{total_repos}")
    print(f"✅ Successfully uploaded: {len(uploaded_batches)}/{target_count}")
    print(f"📈 Progress: {len(uploaded_batches)}/{target_count} batches uploaded")
    print(f"{'='*60}\n")

def main():
    parser = argparse.ArgumentParser(description="Create LT batches from repositories.")
    parser.add_argument("target_language", nargs='?', default=TARGET_LANGUAGE, 
                       help=f"The target language to process (e.g., JavaScript, Python). Default: {TARGET_LANGUAGE}")
    parser.add_argument("--manual", nargs='+', help="A manual list of repositories to process (e.g., 'user/repo1 user/repo2').")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help=f"Number of top repositories to fetch from the sheet. Default: {DEFAULT_COUNT}")
    parser.add_argument("--upload-mode", choices=['All', 'Good', 'Logical'], default=UPLOAD_MODE,
                       help="Upload filtering mode: All (all PRs), Good (only Good PRs), Logical (all PRs in reports). Default: {UPLOAD_MODE}")
    parser.add_argument("--max-retries", type=int, default=3, help="Maximum number of retry attempts for webpage scraping. Default: 3")
    parser.add_argument("--retry-delay", type=int, default=10, help="Delay in seconds between retry attempts. Default: 10")
    parser.add_argument("--no-cache", action="store_true", help="Disable caching for fresh data")
    args = parser.parse_args()

    # Use configured values if not provided via command line
    target_language = args.target_language
    manual_repos = args.manual if args.manual else (MANUAL_REPO_LIST if USE_MANUAL_REPOS else None)
    count = args.count
    upload_mode = args.upload_mode
    max_retries = args.max_retries
    retry_delay = args.retry_delay
    if args.no_cache:
        print("⚠️ Disabling caching for fresh data.")
        clear_cache()

    print(f"=== Repository Batch Creation ===")
    print(f"Target Language: {target_language}")
    print(f"Count: {count}")
    print(f"Upload Mode: {upload_mode}")
    print(f"Repos source: {manual_repos if manual_repos else 'Using sheet data'}")
    if target_language == TARGET_LANGUAGE and not manual_repos and upload_mode == UPLOAD_MODE:
        print(f"(Using configured defaults from script)")
    print("=" * 40)

    # Get language-specific configurations
    lang_config = get_language_config(target_language)
    sheet_name = get_language_sheet_name(target_language)
    project_id = get_language_project_id(target_language)
    json_folder = get_language_json_folder(target_language)
    csv_folder = get_language_csv_folder(target_language)

    # Create folders if they don't exist
    os.makedirs(json_folder, exist_ok=True)
    os.makedirs(csv_folder, exist_ok=True)

    repo_list = []
    if manual_repos:
        repo_list = manual_repos
        print(f"Using manual repository list: {repo_list}")
    else:
        creds_path = os.path.join(os.path.dirname(__file__), 'creds.json')
        from config_utils import get_spreadsheet_key
        spreadsheet_key = get_spreadsheet_key()
        repo_list = get_repos_from_sheet(sheet_name, creds_path, spreadsheet_key, count)
        
        # Check if we got any repositories from the sheet
        if not repo_list:
            print("❌ No qualifying repositories found in Google Sheet.")
            print("💡 Suggestions:")
            print("  - Check if repositories have 'Good PRs > 2' = Yes")
            print("  - Check if repositories have 'Added' = No")
            print("  - Verify the Google Sheet has the correct column names")
            print("  - Check if the sheet contains any data")
            print(f"  - Verify you're using the correct sheet: {sheet_name}")
            return

        # Display initial repository count
        print(f"\n📋 Found {len(repo_list)} qualifying repositories to process")
        display_progress(0, len(repo_list), [], count)

    # Step 1: Fetch existing repositories from LT for the target language only
    print(f"\n🔍 Fetching existing repositories from Labeling Tool for {target_language} (Project ID: {project_id})...")
    existing_repos = set()
    
    try:
        repo_data = fetch_existing_repos_for_project(project_id)
        if repo_data and repo_data.get("data"):
            for batch in repo_data["data"]:
                repo_name = batch.get("name", "Unknown")
                if repo_name != "Unknown":
                    existing_repos.add(repo_name)
            print(f"✅ Found {len(existing_repos)} existing repositories in {target_language} project")
        else:
            print(f"✅ No existing repositories found in {target_language} project")
    except Exception as e:
        print(f"❌ Error fetching existing repositories for {target_language}: {e}")
        existing_repos = set()  # Continue with empty set if there's an error

    # Step 2: Process repositories one by one until we get desired count
    print(f"\n🎯 Target: {count} successful batch{'es' if count != 1 else ''}")
    print(f"📋 Available repositories: {len(repo_list)}")
    
    # Clear cache to ensure fresh data
    if not args.no_cache:
        clear_cache()
    
    uploaded_batches = []
    processed_repos = 0
    json_files_created = []  # Track created JSON files
    processing_stats = []  # Track processing statistics for reporting
    
    # Display progress before starting processing
    display_progress(processed_repos, len(repo_list), uploaded_batches, count)
    
    for i, repo in enumerate(repo_list, 1):
        if len(uploaded_batches) >= count:
            print(f"\n🎉 Target count ({count}) reached! Stopping processing.")
            break
            
        print(f"\n--- Processing {i}/{len(repo_list)}: {repo} ---")
        print(f"📈 Progress: {len(uploaded_batches)}/{count} successful uploads")
        
        repo_name_safe = repo.replace("/", "__")
        processed_repos += 1
        
        # Check if repo already exists in LT
        if repo_name_safe in existing_repos:
            print(f"⏭️ Skipping {repo} - already exists in LT")
            display_progress(processed_repos, len(repo_list), uploaded_batches, count)
            continue
        
        # Use the exact original working method (simplified)
        try:
            pr_list = add_repo_simple(repo_name_safe, target_language, max_retries, retry_delay)
            if not pr_list:
                print(f"❌ No PRs found for {repo}")
                continue
        except Exception as e:
            print(f"❌ Error in add_repo_simple for {repo}: {e}")
            import traceback
            traceback.print_exc()
            continue
        
        json_file_path = os.path.join(json_folder, f"{repo_name_safe}_pr_data.json")
        
        # Add repo name to each PR object for processing
        for pr in pr_list:
            pr['repo'] = repo
        
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(pr_list, f, indent=2)
        print(f"✅ Saved {len(pr_list)} PRs to {json_file_path}")
        json_files_created.append(json_file_path)
        
        # Process this single JSON file
        csv_file_path = os.path.join(csv_folder, f"{repo_name_safe}_pr_data.csv")
        
        try:
            result = process_json_file(
                input_file=json_file_path,
                output_file=csv_file_path,
                existing_repos=existing_repos,
                force=False,
                base_dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # Root directory (parent of src)
                language=target_language,
                upload_mode=upload_mode, # Pass the upload mode
                max_retries=max_retries, # Pass retry parameters
                retry_delay=retry_delay # Pass retry parameters
            )
            
            if result and isinstance(result, dict):
                if result.get('success', False):
                    final_count = result.get('final_pr_count', 0)
                    if final_count > 0:
                        print(f"🔄 {final_count} PRs passed filtering, uploading to LT...")
                        
                        # Upload to LT
                        try:
                            batch_url = create_lt_batch(repo_name_safe, csv_file_path, project_id)
                            print(f"✅ Batch for {repo_name_safe} created at {batch_url}")
                            uploaded_batches.append((repo_name_safe, batch_url))
                            display_progress(processed_repos, len(repo_list), uploaded_batches, count)
                        except Exception as e:
                            print(f"❌ Error uploading {repo}: {e}")
                    else:
                        print(f"⏭️ Skipping {repo} - no usable PRs after filtering (final count: {final_count})")
                        # Add to processing stats for reporting
                        processing_stats.append({
                            'repo_name': repo_name_safe,
                            'language': target_language,
                            'upload_mode': upload_mode,
                            'initial_pr_count': result.get('initial_pr_count', 0),
                            'after_date_filter_count': result.get('after_date_filter_count', 0),
                            'after_good_prs_filter_count': result.get('after_good_prs_filter_count', 0),
                            'after_lt_dedup_count': result.get('after_lt_dedup_count', 0),
                            'after_local_dedup_count': result.get('after_local_dedup_count', 0),
                            'final_pr_count': 0,
                            'good_prs_in_reports': result.get('good_prs_in_reports', 0),
                            'missing_good_prs_count': result.get('missing_good_prs_count', 0),
                            'success': True,
                            'error': ''
                        })
                        display_progress(processed_repos, len(repo_list), uploaded_batches, count)
                else:
                    print(f"❌ Error processing {repo}: {result.get('error', 'Unknown error')}")
                    # Add error to processing stats
                    processing_stats.append({
                        'repo_name': repo_name_safe,
                        'language': target_language,
                        'upload_mode': upload_mode,
                        'initial_pr_count': result.get('initial_pr_count', 0),
                        'after_date_filter_count': result.get('after_date_filter_count', 0),
                        'after_good_prs_filter_count': result.get('after_good_prs_filter_count', 0),
                        'after_lt_dedup_count': result.get('after_lt_dedup_count', 0),
                        'after_local_dedup_count': result.get('after_local_dedup_count', 0),
                        'final_pr_count': 0,
                        'good_prs_in_reports': result.get('good_prs_in_reports', 0),
                        'missing_good_prs_count': result.get('missing_good_prs_count', 0),
                        'success': False,
                        'error': result.get('error', 'Unknown error')
                    })
                    display_progress(processed_repos, len(repo_list), uploaded_batches, count)
            else:
                print(f"⏭️ Skipping {repo} - file already exists or no processing needed")
                display_progress(processed_repos, len(repo_list), uploaded_batches, count)
                
        except Exception as e:
            print(f"❌ Error processing {repo}: {e}")
            # Add error to processing stats
            processing_stats.append({
                'repo_name': repo_name_safe,
                'language': target_language,
                'upload_mode': upload_mode,
                'initial_pr_count': 0,
                'after_date_filter_count': 0,
                'after_good_prs_filter_count': 0,
                'after_lt_dedup_count': 0,
                'after_local_dedup_count': 0,
                'final_pr_count': 0,
                'good_prs_in_reports': 0,
                'missing_good_prs_count': 0,
                'success': False,
                'error': str(e)
            })
            display_progress(processed_repos, len(repo_list), uploaded_batches, count)
    
    # Final progress display
    display_progress(processed_repos, len(repo_list), uploaded_batches, count)
    
    print(f"\n Processing Summary:")
    print(f"  - Repositories checked: {processed_repos}")
    print(f"  - JSON files created: {len(json_files_created)}")
    print(f"  - Target count: {count}")
    print(f"  - Successful uploads: {len(uploaded_batches)}")
    print(f"  - Remaining qualifying repos: {len(repo_list) - processed_repos}")
    
    if len(uploaded_batches) == 0:
        print(f"\n❌ NO BATCHES WERE UPLOADED")
        print(f"💡 Possible reasons:")
        print(f"  - All repositories already exist in LT")
        print(f"  - No PRs found via SWE Bench Plus API")
        print(f"  - All PRs were filtered out (date, Good PR, or deduplication)")
        print(f"  - API errors or timeouts")
        print(f"  - Network connectivity issues")
        if len(json_files_created) > 0:
            print(f"  - Check the JSON files in {json_folder} for debugging")
        return
    elif len(uploaded_batches) < count and processed_repos < len(repo_list):
        print(f"⚠️  Stopped before reaching target count. {len(repo_list) - processed_repos} repositories remain unprocessed.")
    elif len(uploaded_batches) < count:
        print(f"⚠️  Could not reach target count. All {len(repo_list)} qualifying repositories have been processed.")
    
    # Step 3: Final Summary
    print(f"\n{'='*60}")
    print("🎉 BATCH CREATION SUMMARY")
    print(f"{'='*60}")
    print(f"Repositories processed: {processed_repos}")
    print(f"JSON files created: {len(json_files_created)}")
    print(f"Batches uploaded to LT: {len(uploaded_batches)}")
    
    if uploaded_batches:
        print(f"\n📋 UPLOADED BATCHES:")
        for repo_name, batch_url in uploaded_batches:
            print(f"  - {repo_name}: {batch_url}")
        print(f"\n⚠️  IMPORTANT: Visit the Labeling Tool to enable the batches!")
    
    print(f"\n📁 Files saved to:")
    print(f"  - JSON files: {json_folder}")
    print(f"  - CSV files: {csv_folder}")
    
    print(f"\n🎯 Target Achievement:")
    if len(uploaded_batches) >= count:
        print(f"✅ SUCCESS: Reached target of {count} batch{'es' if count != 1 else ''}!")
    else:
        print(f"⚠️  PARTIAL: {len(uploaded_batches)}/{count} batches uploaded")
    
    # Create processing report
    if processing_stats:
        try:
            from convert import create_processing_report
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Root directory
            report_path = create_processing_report(processing_stats, base_dir)
            print(f"\n📊 Processing report created: {report_path}")
        except Exception as e:
            print(f"❌ Error creating processing report: {e}")

if __name__ == "__main__":
    main()
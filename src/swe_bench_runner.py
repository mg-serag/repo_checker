#!/usr/bin/env python3
"""
SWE-Bench Job Runner (updated)
--------------------------------
Variation of `swe-bench_LT (obsolete).py` that:
1. Retrieves tokens from config.json via config_utils
2. Treats `PERSONAL_LT_TOKEN` and `LT_TOKEN` as the same (Labeling-Tool token)
3. Uses the current `convert.process_json_file` signature
4. Can be invoked directly from another script (no CLI parsing)

Usage (from another script / interactive session):

    import swe_bench_runner as sbr
    sbr.REPO_LIST = ["openshift/console", "vuejs/core"]
    sbr.main()

The script will:
• Start / reuse a "get_relevant_prs" SWE-Bench job per repo
• Poll until completion
• Scrape PR rows from the repo page
• Save raw JSON and processed CSV files alongside the script (or in custom folders)
• Create an LT batch in the configured project and print the batch URL
"""

import json
import os
import time
import requests
from bs4 import BeautifulSoup
from diskcache import FanoutCache

# Token & config helpers
from config_utils import (
    get_lt_token,
    get_swe_token,
    get_language_json_folder,
    get_language_csv_folder,
)

from convert import process_json_file

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
# Configuration
# ---------------------------------------------------------------------------

# Tokens (read once at import)
PERSONAL_LT_TOKEN = get_lt_token()  # Same as LT_TOKEN
LT_TOKEN = PERSONAL_LT_TOKEN        # Alias for clarity
SWE_TOKEN = get_swe_token()

# Default language settings (adjust if needed)
TARGET_LANGUAGE = "JavaScript"
PROJECT_ID = 41  # Default JS project – adjust for other languages

# Upload filtering mode - controls which PRs to include in the final CSV
# All: Upload all PRs found in the JSON file (only do deduplication step to remove PRs already in SWE Bench)
# Good: Filter to include only Good PRs (PRs marked as "Good PR" in the PR reports)
# Logical: Filter to include all PRs in the PR report whether the agent judged them as good or bad
UPLOAD_MODE = 'All'  # Options: 'All', 'Good', 'Logical'

# Where to store data files (language-specific folders from language_configs)
JSON_FOLDER = get_language_json_folder(TARGET_LANGUAGE)
CSV_FOLDER = get_language_csv_folder(TARGET_LANGUAGE)

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

# Repositories to process – modify as needed before calling main()
REPO_LIST = [
    "Leaflet/Leaflet",
]

# ---------------------------------------------------------------------------
# Data Processing Helpers
# ---------------------------------------------------------------------------

def _construct_swe_url(instance_id: str) -> str:
    """Construct the SWE URL from repository name and instance ID.
    
    Args:
        repo_name: Repository name in USER__REPO format
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
    
    print(f"🔍 DEBUG: Processing {len(pr_rows)} PR rows")
    if pr_rows:
        print(f"🔍 Available fields in raw data: {list(pr_rows[0].keys())}")
    
    for i, row in enumerate(pr_rows):
        if not isinstance(row, dict):
            print(f"⚠️ Row {i} is not a dict, skipping")
            continue
            
        # Create a copy to avoid modifying the original
        processed_row = row.copy()
        
        # Add repo field if not present
        if 'repo' not in processed_row:
            processed_row['repo'] = repo_name.replace('__', '/')
            print(f"🔧 Row {i}: Added repo field")
        
        # Try to find instance_id from various sources
        instance_id = None
        
        # First, check if instance_id is directly available
        if 'instance_id' in processed_row and processed_row['instance_id']:
            instance_id = str(processed_row['instance_id'])
            print(f"🔧 Row {i}: Found instance_id: {instance_id}")
        
        
        # Construct swe_url if missing
        if 'swe_url' not in processed_row or not processed_row['swe_url']:
            if instance_id:
                processed_row['swe_url'] = _construct_swe_url(instance_id)
                print(f"🔧 Row {i}: Constructed swe_url: {processed_row['swe_url']}")
            else:
                print(f"⚠️ Row {i}: Could not construct swe_url - missing instance_id")
                print(f"   Available fields: {list(processed_row.keys())}")
        
        # Ensure pr_id is present
        if 'pr_id' not in processed_row or not processed_row['pr_id']:
            if instance_id:
                processed_row['pr_id'] = instance_id
                print(f"🔧 Row {i}: Set pr_id from instance_id: {processed_row['pr_id']}")
            else:
                print(f"⚠️ Row {i}: Could not set pr_id - missing instance_id")
        
        processed_rows.append(processed_row)
    
    print(f"✅ Processed {len(processed_rows)} rows successfully")
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
    res = requests.get(url, cookies=_AUTH_COOKIES, headers=_DEFAULT_HEADERS)
    if res.status_code != 200:
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
    res = requests.post(url, json=payload, cookies=_AUTH_COOKIES, headers=_DEFAULT_HEADERS)
    if res.status_code != 200 or "application/json" not in res.headers.get("Content-Type", ""):
        print(f"❌ Failed to start job for {repo_name}: {res.text[:200]}")
        return None
    return res.json().get("jobId")


def _get_job_status(job_id: str) -> str:
    url = f"https://swe-bench-plus.turing.com/api/jobs/{job_id}"
    res = requests.get(url, cookies=_AUTH_COOKIES, headers=_DEFAULT_HEADERS)
    if res.status_code != 200:
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
            r = requests.get(url, cookies=_AUTH_COOKIES, headers={"Accept": "text/html"})
            print(f"🔍 Response status: {r.status_code}")
            
            if r.status_code != 200:
                print(f"❌ HTTP {r.status_code} for {repo_name}")
                print(f"🔍 Response text preview: {r.text[:200]}...")
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
                print(f"🔍 Available script tags: {[s.get('id', 'no-id') for s in soup.find_all('script')]}")
                if attempt < max_retries - 1:
                    print(f"⏳ Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    return []
            
            try:
                data = json.loads(script.text)
                print(f"🔍 Successfully parsed JSON data")
                print(f"🔍 Data structure: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                
                if isinstance(data, dict) and 'props' in data:
                    props = data['props']
                    print(f"🔍 Props structure: {list(props.keys()) if isinstance(props, dict) else 'Not a dict'}")
                    
                    if isinstance(props, dict) and 'pageProps' in props:
                        page_props = props['pageProps']
                        print(f"🔍 PageProps structure: {list(page_props.keys()) if isinstance(page_props, dict) else 'Not a dict'}")
                        
                        if isinstance(page_props, dict) and 'rows' in page_props:
                            rows = page_props['rows']
                            print(f"✅ Found {len(rows) if isinstance(rows, list) else 'non-list'} rows")
                            
                            if isinstance(rows, list) and rows:
                                print(f"🔍 First row keys: {list(rows[0].keys())}")
                                print(f"🔍 Sample row data: {json.dumps(rows[0], indent=2)[:500]}...")
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
                print(f"🔍 Script content preview: {script.text[:200]}...")
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
# LT Batch Creation (unchanged)
# ---------------------------------------------------------------------------


def _create_lt_batch(repo_name_safe: str, csv_path: str) -> str:
    """Upload CSV, create batch, return batch URL."""
    upload_url = "https://eval.turing.com/api/batches/upload/rlhf-metadata"
    create_url = "https://eval.turing.com/api/batches"
    import_url_tmpl = "https://eval.turing.com/api/batches/{}/import-rlhf"

    # 1. Upload file
    with open(csv_path, "rb") as f:
        up_res = requests.post(
            upload_url,
            data={"project_type": "rlhf"},
            files={"file": f},
            headers={"Authorization": f"Bearer {PERSONAL_LT_TOKEN}"},
        )
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
    create_res = requests.post(create_url, json=batch_payload, headers={"Authorization": f"Bearer {PERSONAL_LT_TOKEN}"})
    batch_id = create_res.json()["id"]

    # 3. Trigger import
    requests.post(import_url_tmpl.format(batch_id), json=batch_payload, headers={"Authorization": f"Bearer {PERSONAL_LT_TOKEN}"})

    return f"https://eval.turing.com/batches/{batch_id}/view"


# ---------------------------------------------------------------------------
# High-level repo processing
# ---------------------------------------------------------------------------

def _process_single_repo(repo: str):
    repo_safe = repo.replace("/", "__")

    # 1. Job handling
    job_id = _get_job_id(repo_safe) or _start_job(repo_safe)
    if not job_id:
        print(f"❌ Could not start job for {repo}")
        return

    # 2. Wait for completion
    while True:
        status = _get_job_status(job_id)
        print(f"⏳ {repo} – job {job_id} status: {status}")
        if status == "COMPLETED":
            break
        if status in {"FAILED", "CANCELLED"}:
            print(f"❌ Job failed for {repo}")
            return
        time.sleep(10)

    # Add delay after job completion to ensure webpage data is loaded
    time.sleep(1)

    # 3. Scrape PR rows
    pr_rows = _get_pr_rows_via_web(repo_safe)
    if not pr_rows:
        print(f"❌ No PR data found for {repo}")
        return

    print(f"🔍 DEBUG: PR rows analysis:")
    print(f"   Number of PR rows: {len(pr_rows)}")
    if pr_rows:
        print(f"   Type of first row: {type(pr_rows[0])}")
        print(f"   Keys in first row: {list(pr_rows[0].keys()) if isinstance(pr_rows[0], dict) else 'Not a dict'}")
        
        # Check for essential fields
        essential_fields = ['pr_id', 'swe_url', 'issue_id']
        missing_fields = []
        for field in essential_fields:
            if field not in pr_rows[0]:
                missing_fields.append(field)
        
        if missing_fields:
            print(f"   ⚠️ Missing essential fields in first row: {missing_fields}")
        else:
            print(f"   ✅ All essential fields present in first row")
        
        # Show sample data
        print(f"   Sample PR data: {json.dumps(pr_rows[0], indent=2)[:300]}...")

    # Process PR data to ensure all required fields are present
    print(f"🔧 Processing PR data to add missing fields...")
    processed_pr_rows = _process_pr_data(pr_rows, repo_safe)
    print(f"✅ Processed {len(processed_pr_rows)} PR rows")

    # Re-check essential fields after processing
    if processed_pr_rows:
        print(f"🔍 DEBUG: After processing - first row keys: {list(processed_pr_rows[0].keys())}")
        
        # Check for essential fields again
        essential_fields = ['pr_id', 'swe_url', 'issue_id']
        missing_fields = []
        for field in essential_fields:
            if field not in processed_pr_rows[0]:
                missing_fields.append(field)
        
        if missing_fields:
            print(f"   ⚠️ Still missing essential fields: {missing_fields}")
        else:
            print(f"   ✅ All essential fields now present")
        
        # Show sample processed data
        print(f"   Sample processed PR data: {json.dumps(processed_pr_rows[0], indent=2)[:300]}...")

    # 4. Save raw JSON
    json_path = os.path.abspath(os.path.join(JSON_FOLDER, f"{repo_safe}_pr_data.json"))
    for row in processed_pr_rows:
        row["repo"] = repo  # add repo field expected by convert
    try:
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(processed_pr_rows, jf, indent=2)
        print(f"💾 Saved JSON ⇒ {json_path} ({len(processed_pr_rows)} PRs)")
        
        # Verify the saved file
        print(f"🔍 DEBUG: Verifying saved JSON file...")
        with open(json_path, "r", encoding="utf-8") as jf:
            saved_data = json.load(jf)
        print(f"   Saved file contains {len(saved_data)} PRs")
        if saved_data:
            print(f"   First saved PR keys: {list(saved_data[0].keys())}")
            
    except Exception as e:
        print(f"❌ ERROR: Failed to save JSON file {json_path}: {e}")
        return

    # 5. Convert to CSV using updated signature
    csv_path = os.path.abspath(os.path.join(CSV_FOLDER, f"{repo_safe}_pr_data.csv"))
    
    print(f"🔍 DEBUG: About to call process_json_file:")
    print(f"   JSON file: {json_path}")
    print(f"   CSV file: {csv_path}")
    print(f"   JSON folder: {JSON_FOLDER}")
    print(f"   CSV folder: {CSV_FOLDER}")
    print(f"   JSON folder exists: {os.path.exists(json_path)}")
    print(f"   CSV folder exists: {os.path.exists(CSV_FOLDER)}")
    print(f"   JSON file exists: {os.path.exists(json_path)}")
    print(f"   CSV file exists: {os.path.exists(csv_path)}")
    
    try:
        result = process_json_file(
            input_file=json_path,
            output_file=csv_path,
            existing_repos=set(),
            force=False,
            base_dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # Root directory (parent of src)
            language=TARGET_LANGUAGE,
            upload_mode=UPLOAD_MODE,
        )
        print(f"✅ process_json_file completed successfully")
        if isinstance(result, dict):
            print(f"📊 Result: {result}")
            final_count = result.get('final_pr_count', 0)
            if final_count == 0:
                print(f"⚠️ No usable PRs found for {repo} after filtering")
                print(f"   This could be due to:")
                print(f"   - All PRs were filtered out by date")
                print(f"   - All PRs were filtered out by {UPLOAD_MODE} mode filtering")
                print(f"   - All PRs were already in labeling tool")
                print(f"   - All PRs were already in local files")
                return  # Skip LT upload for empty results
    except Exception as e:
        print(f"❌ ERROR in process_json_file: {e}")
        import traceback
        traceback.print_exc()
        return

    # 6. Upload to LT
    batch_url = _create_lt_batch(repo_safe, csv_path)
    print(f"✅ Batch created: {batch_url}\n")


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def main():
    print("=== SWE-Bench Runner ===")
    print(f"Target language : {TARGET_LANGUAGE}")
    print(f"Project ID      : {PROJECT_ID}")
    print(f"Repos to process: {len(REPO_LIST)}\n")

    # Clear cache to ensure fresh data
    _clear_cache()

    for repo in REPO_LIST:
        try:
            _process_single_repo(repo)
        except Exception as exc:
            print(f"❌ Unexpected error processing {repo}: {exc}")


if __name__ == "__main__":
    main() 
#!/home/amir/.venv_base/bin/python3
"""
Logical Repository Checker

This script evaluates repositories and automatically moves them to appropriate sheets based on their majority language.
Repositories with languages not configured in language_configs.json are moved to the "Scrap" sheet.

Key Changes:
- No longer updates "Already Exists" column (Column H)
- Deletes duplicate repositories instead of marking them
- Processes repositories existing in labeling tool for data collection
- Maintains clean spreadsheet by removing duplicates

Supported languages (configured in language_configs.json):
- Python, JavaScript, TypeScript, Java, Go, C/C++, Ruby, Rust, C#

Any other language detected will be moved to the "Scrap" sheet.
"""

import requests
from requests.exceptions import RequestException
from termcolor import colored
import json
import os
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import time
from datetime import datetime
from typing import Dict

# --- Script Configuration ---
CREDS_JSON_PATH = os.path.join(os.path.dirname(__file__), 'creds.json')
SCOPE = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
from config_utils import get_spreadsheet_key
SPREADSHEET_KEY = get_spreadsheet_key()

# --- Language Configuration ---
# Set the target language for evaluation
TARGET_LANGUAGE = 'JavaScript'  # Options: 'Java', 'JavaScript', 'Python', 'Go', 'C/C++', 'Rust', 'C#'

# Language-specific configurations
from config_utils import (
    get_language_config, get_language_sheet_name, get_language_evaluation_config,
    get_language_target_language, get_project_id, get_language_evaluation_settings,
    get_gspread_client, get_google_sheet
)
from sheet_organizer import (
    get_destination_sheet_for_language, check_repo_exists_in_sheet, 
    process_single_repo_movement
)

# Get current language configuration
LANG_CONFIG = get_language_config(TARGET_LANGUAGE)
SHEET_NAME = get_language_sheet_name(TARGET_LANGUAGE)

# Add project_id to the language config for backward compatibility
LANG_CONFIG['project_id'] = get_project_id(TARGET_LANGUAGE.lower())

# --- Labeling Tool Configuration ---
from config_utils import get_lt_token, get_project_id
LT_TOKEN = get_lt_token()

# --- Column Configuration ---
# Define expected column headers and their default indices (0-based)
# Modify these to match your sheet's structure
COLUMN_CONFIG = {
    'user_repo': {
        'headers': ['repository'],  # Possible header names (case-insensitive)
        'default_index': 0,  # Column A
        'description': 'Repository name in USER/REPO format'
    },
    'repo_url': {
        'headers': ['actual repository link'],
        'default_index': 2,  # Column C
        'description': 'Full GitHub repository URL'
    },
    'majority_language': {
        'headers': ['majority language'],
        'default_index': 3,  # Column D
        'description': 'Primary programming language'
    },
    'percentage': {
        'headers': ['%'],
        'default_index': 4,  # Column E
        'description': 'Percentage of majority language'
    },
    'stars': {
        'headers': ['stars'],
        'default_index': 5,  # Column F
        'description': 'GitHub star count'
    },
    'loc': {
        'headers': ['loc'],
        'default_index': 6,  # Column G
        'description': 'Lines of code count'
    },
    'already_exists': {
        'headers': ['already exists'],
        'default_index': 7,  # Column H
        'description': 'Whether repo already exists or is duplicate'
    },
    'logical_checks': {
        'headers': ['logical checks'],
        'default_index': 8,  # Column I
        'description': 'Result of logical evaluation checks'
    },
    'added': {
        'headers': ['added'],
        'default_index': 14,  # Column O
        'description': 'Whether repo was added to final list'
    },
    'tasks_count_lt': {
        'headers': ['tasks count in lt'],
        'default_index': 15,  # Column P
        'description': 'Total tasks count in labeling tool'
    },
    'improper_lt': {
        'headers': ['improper in lt'],
        'default_index': 16,  # Column Q
        'description': 'Count of improper tasks in labeling tool'
    },
    'batch_link': {
        'headers': ['batch link'],
        'default_index': 17,  # Column R
        'description': 'Link to the batch in labeling tool'
    },
    'addition_date': {
        'headers': ['addition date'],
        'default_index': 18,  # Column S
        'description': 'Date when the repository was added to labeling tool'
    }
}

# --- GitHub API Request Handling ---

def make_github_api_request(url):
    """
    Makes a request to the GitHub API using the GITHUB_TOKEN environment variable.
    """
    github_token = os.getenv('GITHUB_TOKEN')
    if not github_token:
        raise ValueError("GITHUB_TOKEN environment variable not set.")
    
    headers = {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {github_token}"}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403 and 'rate limit exceeded' in e.response.text.lower():
            print(colored(f"Rate limit exceeded for GitHub API. Please wait and try again.", "red"))
            # Get reset time from headers if available
            reset_time_utc = int(e.response.headers.get('X-RateLimit-Reset', time.time() + 3600))
            wait_time = max(reset_time_utc - time.time(), 0) + 5  # Add a 5-second buffer
            print(colored(f"Waiting for {int(wait_time)} seconds until reset...", "red"))
            time.sleep(wait_time)
            # Retry once after waiting
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response
        else:
            # It's a different HTTP error (e.g., 404 Not Found), so we should stop and report it.
            print(colored(f"An unexpected HTTP error occurred: {e}", "red"))
            raise e

# --- Labeling Tool API Functions ---

def fetch_existing_repos_from_lt():
    """
    Fetches all batch data from the labeling tool API for the current project.
    Returns a list of repository names that already exist in the labeling tool.
    """
    project_id = LANG_CONFIG['project_id']
    
    # Check if project ID is a placeholder (non-existent)
    if project_id in [999]:  # Placeholder IDs (none currently)
        print(colored(f"\n[Labeling Tool] Project ID {project_id} is a placeholder. Skipping labeling tool checks for {TARGET_LANGUAGE}.", "yellow"))
        return set()
    
    base_url = f"https://eval.turing.com/api/batches?sort%5B0%5D=createdAt%2CDESC&join%5B0%5D=batchStats&join%5B1%5D=importAttempts&filter%5B0%5D=projectId%7C%7C%24eq%7C%7C{project_id}"
    headers = {"Authorization": f"Bearer {LT_TOKEN}"}
    all_batches = []
    page = 1
    limit = 100

    print(f"\n[Labeling Tool] Fetching existing repos for {TARGET_LANGUAGE} project (ID: {project_id})...")

    while True:
        paginated_url = f"{base_url}&limit={limit}&page={page}"
        try:
            response = requests.get(paginated_url, headers=headers)
            response.raise_for_status()
            json_data = response.json()
            batches_on_page = json_data.get("data")
            if not batches_on_page:
                break
            all_batches.extend(batches_on_page)
            if len(batches_on_page) < limit:
                break
            page += 1
        except requests.exceptions.RequestException as e:
            print(colored(f"Error fetching batches from labeling tool: {e}", "red"))
            return set()

    # Extract repository names and convert from USER__REPO to USER/REPO format
    existing_repos = set()
    for batch in all_batches:
        batch_name = batch.get("name", "")
        if batch_name and "__" in batch_name:
            # Convert USER__REPO to USER/REPO
            repo_name = batch_name.replace("__", "/")
            existing_repos.add(repo_name.lower())  # Store in lowercase for case-insensitive comparison

    print(f"[Labeling Tool] Found {len(existing_repos)} existing repositories in labeling tool")
    return existing_repos

def fetch_all_batches_from_lt():
    """
    Fetches all batch data from the labeling tool API for the current project.
    Returns a dictionary mapping USER__REPO to batch data.
    """
    project_id = LANG_CONFIG['project_id']
    
    # Check if project ID is a placeholder (non-existent)
    if project_id in [999]:  # Placeholder IDs (none currently)
        print(colored(f"\n[Labeling Tool] Project ID {project_id} is a placeholder. Skipping labeling tool data fetch for {TARGET_LANGUAGE}.", "yellow"))
        return {}
    
    base_url = f"https://eval.turing.com/api/batches?sort%5B0%5D=createdAt%2CDESC&join%5B0%5D=batchStats&join%5B1%5D=importAttempts&filter%5B0%5D=projectId%7C%7C%24eq%7C%7C{project_id}"
    headers = {"Authorization": f"Bearer {LT_TOKEN}"}
    all_batches = []
    page = 1
    limit = 100

    print(f"\n[Labeling Tool] Fetching all batch data for {TARGET_LANGUAGE} project (ID: {project_id})...")

    while True:
        paginated_url = f"{base_url}&limit={limit}&page={page}"
        try:
            response = requests.get(paginated_url, headers=headers)
            response.raise_for_status()
            json_data = response.json()
            batches_on_page = json_data.get("data")
            if not batches_on_page:
                break
            all_batches.extend(batches_on_page)
            if len(batches_on_page) < limit:
                break
            page += 1
        except requests.exceptions.RequestException as e:
            print(colored(f"Error fetching batches from labeling tool: {e}", "red"))
            return {}

    # Create a dictionary mapping USER__REPO to batch data
    batch_data = {}
    for batch in all_batches:
        if batch is not None:  # Ensure batch is not None
            batch_name = batch.get("name", "")
            if batch_name and "__" in batch_name:
                batch_data[batch_name] = batch

    print(f"[Labeling Tool] Found {len(batch_data)} batches with valid names")
    return batch_data

def update_data_from_LT(json_path, spreadsheet_key, scope, sheet_name, column_indices):
    """
    Updates the sheet with data from the labeling tool for all repositories.
    Updates columns O (Added), P (Tasks Count in LT), Q (Improper in LT), R (Batch link), and S (Addition Date).
    """
    print("\n=== Starting Labeling Tool Data Update ===")
    
    # Fetch all batch data from labeling tool
    batch_data = fetch_all_batches_from_lt()
    if not batch_data:
        print(colored("No batch data found in labeling tool. Skipping update.", "yellow"))
        return
    
    try:
        # Fetch current sheet data
        client = _get_gspread_client(json_path, scope)
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)
        all_values = sheet.get_all_values()
        
        if not all_values or len(all_values) < 2:
            print(colored("Sheet is empty or has no data rows.", "yellow"))
            return
        
        header = all_values[0]
        data_rows = all_values[1:]
        
        # Get column indices for the new columns
        user_repo_col_idx = column_indices['user_repo']
        added_col_0_idx = column_indices['added']
        
        added_col_idx_1 = column_indices['added'] + 1
        tasks_count_col_idx_1 = column_indices['tasks_count_lt'] + 1
        improper_col_idx_1 = column_indices['improper_lt'] + 1
        batch_link_col_idx_1 = column_indices['batch_link'] + 1
        addition_date_col_idx_1 = column_indices['addition_date'] + 1
        
        # Check if we have enough columns in the data
        max_col_needed = max(user_repo_col_idx, column_indices['added'], 
                           column_indices['tasks_count_lt'], column_indices['improper_lt'], 
                           column_indices['batch_link'], column_indices['addition_date'])
        
        if max_col_needed >= len(data_rows[0]) if data_rows else 0:
            print(colored(f"Warning: Sheet may not have enough columns. Need at least {max_col_needed + 1} columns.", "yellow"))
        
        print(f"Updating columns: O (Added), P (Tasks Count), Q (Improper), R (Batch Link), S (Addition Date)")
        print(f"Processing {len(data_rows)} data rows...")
        print(f"Batch data contains {len(batch_data)} entries")
        
        cell_updates = []
        updated_count = 0
        refreshed_count = 0
        skipped_count = 0
        
        for row_idx, row in enumerate(data_rows):
            sheet_row = row_idx + 2  # Convert to sheet row number
            
            # Ensure row is long enough, otherwise skip
            if user_repo_col_idx >= len(row) or added_col_0_idx >= len(row):
                skipped_count += 1
                continue

            user_repo = row[user_repo_col_idx].strip()
            current_added_status = row[added_col_0_idx].strip().lower()

            # Default: repo not found
            repo_in_lt = None

            # Try to find a match in LT if the repo name is valid
            if user_repo and '/' in user_repo:
                lt_key = user_repo.replace('/', '__')
                if lt_key in batch_data and batch_data[lt_key] is not None:
                    repo_in_lt = batch_data[lt_key]
                elif lt_key in batch_data:
                    print(f"  Warning: Found None batch data for {lt_key}")

            # Apply rules based on "Added" column status
            if current_added_status == 'yes':
                if repo_in_lt:
                    try:
                        # Rule 1: "Yes" row found -> Refresh counts only
                        batch_stats = repo_in_lt.get("batchStats", {}) or {}
                        total_tasks = repo_in_lt.get("countOfConversations", 0) or 0
                        improper_tasks = batch_stats.get("improper", 0) if batch_stats else 0
                        
                        # Parse addition date from createdAt field
                        addition_date = ""
                        created_at = repo_in_lt.get("createdAt")
                        if created_at:
                            try:
                                # Parse ISO format datetime and extract date only
                                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                addition_date = dt.strftime('%Y-%m-%d')
                            except (ValueError, AttributeError) as e:
                                print(f"  Warning: Could not parse createdAt for {user_repo}: {created_at} - {e}")
                        
                        cell_updates.extend([
                            gspread.Cell(sheet_row, tasks_count_col_idx_1, total_tasks),
                            gspread.Cell(sheet_row, improper_col_idx_1, improper_tasks),
                            gspread.Cell(sheet_row, addition_date_col_idx_1, addition_date),
                        ])
                        refreshed_count += 1
                        print(f"  Refreshed counts for existing repo in row {sheet_row}: {user_repo}")
                    except Exception as e:
                        print(f"  Error processing existing repo {user_repo} in row {sheet_row}: {e}")
                # else: Do nothing, as requested for "Yes" rows not found in LT
            
            else:  # Rule 2: "No" or empty "Added" column -> Perform full update
                if repo_in_lt:
                    try:
                        # Full update for newly found repo
                        batch_id = repo_in_lt.get("id")
                        batch_stats = repo_in_lt.get("batchStats", {}) or {}
                        total_tasks = repo_in_lt.get("countOfConversations", 0) or 0
                        improper_tasks = batch_stats.get("improper", 0) if batch_stats else 0
                        batch_link = f"https://eval.turing.com/batches/{batch_id}/view" if batch_id else ""
                        
                        # Parse addition date from createdAt field
                        addition_date = ""
                        created_at = repo_in_lt.get("createdAt")
                        if created_at:
                            try:
                                # Parse ISO format datetime and extract date only
                                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                addition_date = dt.strftime('%Y-%m-%d')
                            except (ValueError, AttributeError) as e:
                                print(f"  Warning: Could not parse createdAt for {user_repo}: {created_at} - {e}")
                        
                        cell_updates.extend([
                            gspread.Cell(sheet_row, added_col_idx_1, "Yes"),
                            gspread.Cell(sheet_row, tasks_count_col_idx_1, total_tasks),
                            gspread.Cell(sheet_row, improper_col_idx_1, improper_tasks),
                            gspread.Cell(sheet_row, batch_link_col_idx_1, batch_link),
                            gspread.Cell(sheet_row, addition_date_col_idx_1, addition_date)
                        ])
                        updated_count += 1
                        print(f"  Updated row {sheet_row}: Found {user_repo} in LT.")
                    except Exception as e:
                        print(f"  Error processing new repo {user_repo} in row {sheet_row}: {e}")
                else:
                    # Mark as "NO" and clear fields
                    cell_updates.extend([
                        gspread.Cell(sheet_row, added_col_idx_1, "No"),
                        gspread.Cell(sheet_row, tasks_count_col_idx_1, ""),
                        gspread.Cell(sheet_row, improper_col_idx_1, ""),
                        gspread.Cell(sheet_row, batch_link_col_idx_1, ""),
                        gspread.Cell(sheet_row, addition_date_col_idx_1, "")
                    ])
        
        # Batch update all cells for efficiency
        if cell_updates:
            sheet.update_cells(cell_updates, value_input_option='USER_ENTERED')
            log_parts = []
            if updated_count > 0:
                log_parts.append(f"marked {updated_count} new repos as added")
            if refreshed_count > 0:
                log_parts.append(f"refreshed counts for {refreshed_count} existing repos")
            if skipped_count > 0:
                log_parts.append(f"skipped {skipped_count} rows with insufficient data")
            
            if log_parts:
                print(colored(f"\nSuccessfully updated sheet: " + " and ".join(log_parts) + ".", "green"))
            else:
                print(colored("\nNo updatable repositories found matching the criteria in the labeling tool.", "yellow"))
        else:
            print(colored("No updates were made.", "yellow"))
            
    except Exception as e:
        print(colored(f"Error updating sheet with labeling tool data: {e}", "red"))
        import traceback
        print(colored(f"Full traceback: {traceback.format_exc()}", "red"))

# --- Google Sheets Helper ---

def get_column_indices(header):
    """
    Get column indices from header using the COLUMN_CONFIG.
    Shows which columns were found by header name vs. using defaults.
    """
    header_lower = [h.lower().strip() for h in header]
    indices = {}
    
    print("\n--- Column Mapping Results ---")
    
    for column_key, config in COLUMN_CONFIG.items():
        found_index = None
        found_header = None
        
        # Try to find the column by header name
        for possible_header in config['headers']:
            try:
                found_index = header_lower.index(possible_header.lower())
                found_header = possible_header
                break
            except ValueError:
                continue
        
        if found_index is not None:
            indices[column_key] = found_index
            excel_col = chr(65 + found_index) if found_index < 26 else f"Column {found_index + 1}"
            print(f"  ✓ {column_key:15} -> {excel_col:8} (found header: '{found_header}')")
        else:
            indices[column_key] = config['default_index']
            excel_col = chr(65 + config['default_index']) if config['default_index'] < 26 else f"Column {config['default_index'] + 1}"
            print(f"  ! {column_key:15} -> {excel_col:8} (using default, expected: {config['headers']})")
    
    print("--- End Column Mapping ---\n")
    return indices

# NOTE: oauth2client is deprecated and can cause JWT signature issues.
# Switch to gspread's built-in service_account helper that relies on
# google-auth under the hood.

# Build a global credentials object lazily so we don't recreate it for every
# Sheets call.
_GCRED = None

def _get_gspread_client(json_path, scopes):
    """Return a cached gspread client authorised with the service account."""
    global _GCRED
    if _GCRED is None:
        _GCRED = Credentials.from_service_account_file(json_path, scopes=scopes)
    return gspread.Client(auth=_GCRED)

def fetch_sheet_data(json_path, spreadsheet_key, scope, sheet_name=None):
    """
    Fetches data and header from a Google Sheet.
    """
    client = _get_gspread_client(json_path, scope)
    spreadsheet = client.open_by_key(spreadsheet_key)

    if sheet_name:
        sheet = spreadsheet.worksheet(sheet_name)
    else:
        sheet = spreadsheet.sheet1  # Default to the first sheet

    all_values = sheet.get_all_values()
    if not all_values:
        return pd.DataFrame(), []
        
    header = all_values[0]
    data = all_values[1:]
    
    # Create a DataFrame with enough columns to match the header length
    df = pd.DataFrame(data, columns=[f'col_{i}' for i in range(len(header))])
    
    return df, header

# --- GitHub API Helpers ---

LOC_CACHE = {}

def get_lines_count(user_repo):
    """
    Get lines of code for a repository using sequential API calls.
    Uses caching to avoid repeated API calls.
    """
    start_time = time.time()
    print(f"\n[LOC Check] Starting LOC check for {user_repo}...")
    
    # Check cache first
    if user_repo in LOC_CACHE:
        elapsed_time = time.time() - start_time
        print(f"[LOC Check] Retrieved from cache in {elapsed_time:.2f} seconds")
        return LOC_CACHE[user_repo]

    def try_codetabs_api(branch=None):
        """Try to get LOC from codetabs API with a specific branch"""
        try:
            url = f"https://api.codetabs.com/v1/loc?github={user_repo}"
            if branch:
                url += f"&branch={branch}"
            
            print(f"[LOC Check] Trying API call for {user_repo}" + (f" (branch: {branch})" if branch else ""))
            response = requests.get(url, timeout=600)  # 10 minute timeout
            if response.status_code == 200:
                data = response.json()
                total_lines = sum([i['linesOfCode'] for i in data if i['language'].lower().strip() == 'total'])
                if total_lines > 0:  # Only return if we got a valid number
                    return total_lines
                print(f"[LOC Check] API returned 0 lines for {user_repo}")
            else:
                print(f"[LOC Check] API returned status code {response.status_code} for {user_repo}")
        except requests.Timeout:
            print(f"[LOC Check] Timeout while fetching LOC for {user_repo}")
        except requests.RequestException as e:
            print(f"[LOC Check] Request failed for {user_repo}: {str(e)}")
        except json.JSONDecodeError:
            print(f"[LOC Check] Invalid JSON response for {user_repo}")
        except Exception as e:
            print(f"[LOC Check] Unexpected error for {user_repo}: {str(e)}")
        return None

    def get_default_branch(owner_repo):
        """Get default branch from GitHub API"""
        try:
            url = f"https://api.github.com/repos/{owner_repo}"
            response = make_github_api_request(url)
            return response.json()["default_branch"]
        except (RequestException, KeyError):
            return "main"  # Fallback to main

    # Try methods sequentially
    # 1. Try without branch first
    result = try_codetabs_api()
    if result is not None:
        LOC_CACHE[user_repo] = result
        elapsed_time = time.time() - start_time
        print(f"[LOC Check] Completed in {elapsed_time:.2f} seconds")
        return result

    # 2. Try with main branch
    result = try_codetabs_api("main")
    if result is not None:
        LOC_CACHE[user_repo] = result
        elapsed_time = time.time() - start_time
        print(f"[LOC Check] Completed in {elapsed_time:.2f} seconds")
        return result

    # 3. Try with default branch
    default_branch = get_default_branch(user_repo)
    result = try_codetabs_api(default_branch)
    if result is not None:
        LOC_CACHE[user_repo] = result
        elapsed_time = time.time() - start_time
        print(f"[LOC Check] Completed in {elapsed_time:.2f} seconds")
        return result

    # If all methods fail, return None
    elapsed_time = time.time() - start_time
    print(f"[LOC Check] Failed after {elapsed_time:.2f} seconds")
    return None


def get_repo_details(user_repo):
    start_time = time.time()
    print(f"\n[Repo Info] Starting repo details fetch for {user_repo}...")
    
    try:
        user, repo = user_repo.split('/')
    except ValueError:
        print("Invalid input format. Please use 'user/repo' format.")
        return None
    
    api_url = f"https://api.github.com/repos/{user}/{repo}"
    languages_url = f"https://api.github.com/repos/{user}/{repo}/languages"
    
    try:
        repo_response = make_github_api_request(api_url)
        repo_data = repo_response.json()
        
        languages_response = make_github_api_request(languages_url)
        languages_data = languages_response.json()
        
        elapsed_time = time.time() - start_time
        print(f"[Repo Info] Completed in {elapsed_time:.2f} seconds")
        
        return {
            'repo_data': repo_data,
            'languages_data': languages_data
        }
    except requests.exceptions.RequestException as e:
        elapsed_time = time.time() - start_time
        print(f"[Repo Info] Failed after {elapsed_time:.2f} seconds")
        print(colored(f"Could not get repo details for {user_repo} due to API error: {e}", "red"))
        return None

# --- Evaluation Logic ---

def get_required_loc_for_stars(stars, loc_thresholds):
    """
    Get the required LOC based on star count using the threshold mapping.
    """
    # Sort thresholds by star count (descending) to find the appropriate threshold
    sorted_thresholds = sorted(loc_thresholds.items(), reverse=True)
    
    for threshold_stars, required_loc in sorted_thresholds:
        if stars >= threshold_stars:
            return required_loc
    
    # If stars are below the minimum threshold, return the highest required LOC
    return max(loc_thresholds.values())



def combine_c_cpp_languages(language_percentages):
    """
    Combine C and C++ percentages as they should be treated as one language group.
    
    Args:
        language_percentages: Dictionary of language -> percentage
        
    Returns:
        Updated language_percentages dict with combined C/C++
    """
    c_percent = language_percentages.get('C', 0)
    cpp_percent = language_percentages.get('C++', 0)
    
    if c_percent > 0 or cpp_percent > 0:
        combined_percent = c_percent + cpp_percent
        
        # Remove individual C/C++ entries
        language_percentages.pop('C', None)
        language_percentages.pop('C++', None)
        
        # Add a single "C/C++" entry
        language_percentages['C/C++'] = combined_percent
        
    return language_percentages


def combine_js_ts_languages(language_percentages):
    """
    Combine JavaScript and TypeScript percentages as they should be treated as one language.
    
    Args:
        language_percentages: Dictionary of language -> percentage
        
    Returns:
        Updated language_percentages dict with combined JS/TS
    """
    js_percent = language_percentages.get('JavaScript', 0)
    ts_percent = language_percentages.get('TypeScript', 0)
    
    if js_percent > 0 or ts_percent > 0:
        combined_percent = js_percent + ts_percent
        
        # Remove individual JS/TS entries
        language_percentages.pop('JavaScript', None)
        language_percentages.pop('TypeScript', None)
        
        # Add combined entry using the more dominant language name, or JavaScript if equal
        if ts_percent > js_percent:
            language_percentages['TypeScript'] = combined_percent
        else:
            language_percentages['JavaScript'] = combined_percent
    
    return language_percentages

def evaluate_repo(user_repo, all_repos_df, column_indices, existing_lt_repos, row_number=None):
    """
    Evaluates a single repository based on a set of criteria.
    Returns a dictionary with detailed results of each check.
    """
    start_time = time.time()
    row_info = f" (Row {row_number})" if row_number else ""
    # Get evaluation settings for the target language
    eval_settings = get_language_evaluation_settings(TARGET_LANGUAGE)
    target_language = get_language_target_language(TARGET_LANGUAGE)
    
    print(f"\n=== Starting evaluation for {user_repo}{row_info} at {datetime.now().strftime('%H:%M:%S')} ===")
    print(f"[Config] Target Language: {target_language}, Min Stars: {eval_settings['min_stars']}, Min Percentage: {eval_settings['min_percentage']}%")
    
    results = {
        'repo': user_repo, 'should_add': False, 'reason': "",
        'language_name': "N/A", 'language_percent': 0, 'star_count': 0, 
        'loc_count': "N/A", 'manual_review': False,
    }

    # Note: We no longer check "already_exists" status - we process all repos
    # Repositories in LT will be processed for data collection
    # Duplicates will be handled by deletion logic in main()

    # 3. Fetch repo details (language and stars)
    details = get_repo_details(user_repo)
    if not details:
        results['reason'] = 'Could not fetch repo details from GitHub API.'
        print(f"=== Evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
        return results

    # 4. Language check - Always output majority language and its percentage
    languages_data = details['languages_data']
    total_bytes = sum(languages_data.values())
    if total_bytes == 0:
        results['reason'] = 'Repo appears to be empty (no code).'
        print(f"=== Evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
        return results
        
    language_percentages = {lang: (bytes / total_bytes) * 100 for lang, bytes in languages_data.items()}
    
    # Combine language variations
    language_percentages = combine_js_ts_languages(language_percentages)
    language_percentages = combine_c_cpp_languages(language_percentages)
    
    # Get the majority language (which might be combined JS/TS)
    primary_lang_name, primary_lang_percent = max(language_percentages.items(), key=lambda x: x[1])
    
    # Check if the primary language matches our target language (for evaluation purposes)
    target_lang_percent = language_percentages.get(target_language, 0)
    
    # Always output the majority language and its percentage
    results.update({
        'language_name': primary_lang_name,
        'language_percent': primary_lang_percent / 100,  # Store as decimal
    })
    
    # 5. Star rating check (>= min_stars)
    stars = details['repo_data'].get('stargazers_count', 0)
    results['star_count'] = stars

    # 6. LOC Check - Always run for evaluation, regardless of target language percentage
    # This ensures we can move repos based on their actual majority language
    lines = None
    print(f"[LOC Check] Running LOC check for {user_repo}{row_info} (Primary Language: {primary_lang_name} {primary_lang_percent:.2f}%, Target Language: {target_language} {target_lang_percent:.2f}%, Stars: {stars})")
    lines = get_lines_count(user_repo)
    
    # Handle LOC results
    if lines is None:
        results['loc_count'] = "ERROR"
        loc_check_passed = False
    elif lines == 0:
        results['loc_count'] = "ERROR 0"
        loc_check_passed = False
    else:
        results['loc_count'] = lines
        # Use evaluation settings for the primary language, not target language
        try:
            primary_lang_eval_settings = get_language_evaluation_settings(primary_lang_name)
            required_loc = get_required_loc_for_stars(stars, primary_lang_eval_settings['loc_thresholds'])
            if lines >= required_loc:
                loc_check_passed = True
            else:
                loc_check_passed = False
        except KeyError:
            # For unconfigured languages, use target language settings as fallback
            print(f"[Evaluation] Language '{primary_lang_name}' not configured, using target language settings")
            required_loc = get_required_loc_for_stars(stars, eval_settings['loc_thresholds'])
            if lines >= required_loc:
                loc_check_passed = True
            else:
                loc_check_passed = False

    # Manual review determination: other checks pass but LOC had an error
    if (stars >= eval_settings['min_stars'] and
        str(results['loc_count']).upper().startswith("ERROR")):
        results['manual_review'] = True

    # Final verdict - Consider both target language and primary language
    # A repo should be added if it meets criteria for its primary language OR target language
    try:
        primary_lang_eval_settings = get_language_evaluation_settings(primary_lang_name)
    except KeyError:
        # For unconfigured languages, use target language settings as fallback
        print(f"[Evaluation] Language '{primary_lang_name}' not configured, using target language settings")
        primary_lang_eval_settings = eval_settings
    
    # Check if repo meets criteria for primary language
    primary_lang_checks_passed = [
        primary_lang_percent >= primary_lang_eval_settings['min_percentage'],
        stars >= primary_lang_eval_settings['min_stars'],
        loc_check_passed
    ]
    
    # Check if repo meets criteria for target language
    target_lang_checks_passed = [
        target_lang_percent >= eval_settings['min_percentage'],
        stars >= eval_settings['min_stars'],
        loc_check_passed
    ]
    
    # Repo should be added if it meets criteria for either language
    results['should_add'] = all(primary_lang_checks_passed) or all(target_lang_checks_passed)
    
    if results['manual_review']:
        results['reason'] = "LOC check error – manual review required"
    elif not results['should_add']:
        reasons = []
        if target_lang_percent < eval_settings['min_percentage'] and primary_lang_percent < primary_lang_eval_settings['min_percentage']:
            reasons.append(f"Language percentage too low (Target: {target_lang_percent:.2f}%, Primary: {primary_lang_percent:.2f}%)")
        if stars < eval_settings['min_stars'] and stars < primary_lang_eval_settings['min_stars']:
            reasons.append(f"Stars < {stars}")
        if not loc_check_passed and lines is not None:
            # Use the more lenient LOC requirement
            target_required_loc = get_required_loc_for_stars(stars, eval_settings['loc_thresholds'])
            primary_required_loc = get_required_loc_for_stars(stars, primary_lang_eval_settings['loc_thresholds'])
            required_loc = min(target_required_loc, primary_required_loc)
            reasons.append(f"LOC < {required_loc:,}")
        results['reason'] = ", ".join(reasons)
    else:
        # Determine which language criteria it passed
        if all(primary_lang_checks_passed) and not all(target_lang_checks_passed):
            results['reason'] = f"Passed criteria for primary language ({primary_lang_name})"
        elif all(target_lang_checks_passed) and not all(primary_lang_checks_passed):
            results['reason'] = f"Passed criteria for target language ({target_language})"
        else:
            results['reason'] = f"Passed criteria for both {primary_lang_name} and {target_language}"

    print(f"=== Evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
    return results

# --- Google Sheets Output ---

def update_sheet_with_results(json_path, spreadsheet_key, scope, sheet_name, repo_url, results, column_indices):
    """
    Updates a single row in the Google Sheet with the evaluation results.
    """
    try:
        client = _get_gspread_client(json_path, scope)
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)

        url_column_index = column_indices['repo_url'] + 1
        url_column_values = sheet.col_values(url_column_index)
        
        try:
            row_index = url_column_values.index(repo_url) + 1
        except ValueError:
            print(colored(f"Could not find URL {repo_url} in the sheet to update.", "red"))
            return

        final_verdict = "Manual" if results.get('manual_review') else ("Yes" if results['should_add'] else "No")
        
        cell_updates = [
            gspread.Cell(row_index, column_indices['majority_language'] + 1, results['language_name']),
            gspread.Cell(row_index, column_indices['percentage'] + 1, results['language_percent']),
            gspread.Cell(row_index, column_indices['stars'] + 1, results['star_count']),
            gspread.Cell(row_index, column_indices['loc'] + 1, str(results['loc_count'])),
            gspread.Cell(row_index, column_indices['logical_checks'] + 1, final_verdict),
        ]
        
        sheet.update_cells(cell_updates, value_input_option='USER_ENTERED')
        print(colored(f"Successfully updated sheet for {results['repo']}.", "blue"))

    except Exception as e:
        print(colored(f"Failed to update sheet for {results['repo']}: {e}", "red"))

# --- Duplicate Detection ---

def identify_duplicates_for_deletion(df, column_indices, existing_lt_repos):
    """
    Identifies duplicate repositories for deletion.
    Returns a list of row indices to delete from the sheet.
    """
    print("--- Identifying Duplicates for Deletion ---")
    
    repo_url_col_idx = column_indices['repo_url']
    user_repo_col_idx = column_indices['user_repo']
    
    repo_url_col_name = f"col_{repo_url_col_idx}"
    user_repo_col_name = f"col_{user_repo_col_idx}"
    
    # Ensure we have enough columns
    if len(df.columns) <= max(repo_url_col_idx, user_repo_col_idx):
        print(colored("Warning: Not enough columns to perform duplicate identification", "yellow"))
        return []
    
    # Get all repository URLs and normalize them
    normalized_urls = df[repo_url_col_name].str.lower().str.strip()
    
    # Find duplicates within the sheet (keep first occurrence, mark rest for deletion)
    duplicate_mask = normalized_urls.duplicated(keep='first')
    # Exclude blank/empty URLs from being considered duplicates
    duplicate_mask &= normalized_urls != ""
    duplicate_count = duplicate_mask.sum()
    
    # Get indices of duplicates to delete
    duplicate_indices = df[duplicate_mask].index.tolist()
    
    if duplicate_count > 0:
        print(f"Found {duplicate_count} duplicate repositories to delete")
        
        # Print duplicate information
        duplicate_urls = normalized_urls[duplicate_mask].unique()
        for url in duplicate_urls:
            if pd.notna(url) and url.strip():
                matching_indices = normalized_urls[normalized_urls == url].index.tolist()
                first_row = matching_indices[0] + 2  # Convert to sheet row number
                duplicate_rows = [idx + 2 for idx in matching_indices[1:]]  # Convert to sheet row numbers
                print(f"  Duplicate found: {url}")
                print(f"    Keeping: Row {first_row}")
                print(f"    Deleting: Rows {duplicate_rows}")
    
    # Note: We no longer mark LT repos as duplicates - we process them for data
    print("Note: Repositories existing in labeling tool will be processed for data collection")
    
    return duplicate_indices

def print_column_configuration():
    """
    Prints the current column configuration for easy reference.
    """
    from config_utils import get_language_evaluation_config, get_loc_thresholds, get_language_target_language
    
    eval_config = get_language_evaluation_config(TARGET_LANGUAGE)
    loc_thresholds = get_loc_thresholds(TARGET_LANGUAGE)
    target_language = get_language_target_language(TARGET_LANGUAGE)
    
    print("=" * 80)
    print("COLUMN CONFIGURATION")
    print("=" * 80)
    print(f"Sheet: {SPREADSHEET_KEY}")
    print(f"Tab: {SHEET_NAME}")
    print(f"Target Language: {target_language}")
    print(f"Min Stars: {eval_config['min_stars']}")
    print(f"Min Language Percentage: {eval_config['min_percentage']}%")
    print(f"Labeling Tool Project ID: {LANG_CONFIG['project_id']}")
    print("-" * 80)
    print("LOC Thresholds:")
    for stars, loc in sorted(loc_thresholds.items()):
        print(f"  {stars} stars -> {loc:,} LOC")
    print("-" * 80)
    print(f"{'Column Key':<18} {'Excel':<8} {'Expected Headers':<25} {'Description'}")
    print("-" * 80)
    
    for column_key, config in COLUMN_CONFIG.items():
        excel_col = chr(65 + config['default_index']) if config['default_index'] < 26 else f"Col {config['default_index'] + 1}"
        headers_str = ", ".join(config['headers'])
        if len(headers_str) > 24:
            headers_str = headers_str[:21] + "..."
        print(f"{column_key:<18} {excel_col:<8} {headers_str:<25} {config['description']}")
    
    print("=" * 80)
    print()



# --- Repository Movement Logic ---

def determine_missing_checks(row, column_indices) -> dict:
    """
    Determine which checks are missing based on existing data in the row.
    
    Args:
        row: DataFrame row containing repository data
        column_indices: Column index mapping
        
    Returns:
        Dictionary indicating which checks need to be performed
    """
    checks_needed = {
        'language_check': False,
        'stars_check': False,
        'loc_check': False,
        'logical_check': False
    }
    
    # Check if majority language (column D) is missing
    majority_lang_col = f"col_{column_indices['majority_language']}"
    if majority_lang_col in row.index:
        lang_val = row[majority_lang_col]
        if pd.isna(lang_val) or str(lang_val).strip() == '':
            checks_needed['language_check'] = True
    else:
        checks_needed['language_check'] = True
    
    # Check if percentage (column E) is missing
    percentage_col = f"col_{column_indices['percentage']}"
    if percentage_col in row.index:
        perc_val = row[percentage_col]
        if pd.isna(perc_val) or str(perc_val).strip() == '':
            checks_needed['language_check'] = True
    else:
        checks_needed['language_check'] = True
    
    # Check if stars (column F) is missing
    stars_col = f"col_{column_indices['stars']}"
    if stars_col in row.index:
        stars_val = row[stars_col]
        if pd.isna(stars_val) or str(stars_val).strip() == '':
            checks_needed['stars_check'] = True
    else:
        checks_needed['stars_check'] = True
    
    # Check if LOC (column G) is missing
    loc_col = f"col_{column_indices['loc']}"
    if loc_col in row.index:
        loc_val = row[loc_col]
        if pd.isna(loc_val) or str(loc_val).strip() == '':
            checks_needed['loc_check'] = True
    else:
        checks_needed['loc_check'] = True
    
    # Check if logical checks (column I) is missing
    logical_col = f"col_{column_indices['logical_checks']}"
    if logical_col in row.index:
        logical_val = row[logical_col]
        if pd.isna(logical_val) or str(logical_val).strip() == '':
            checks_needed['logical_check'] = True
    else:
        checks_needed['logical_check'] = True
    
    return checks_needed


def evaluate_repo_with_resume(user_repo, row, all_repos_df, column_indices, existing_lt_repos, row_number=None):
    """
    Evaluates a repository with resume logic - only performs missing checks.
    
    Args:
        user_repo: Repository name in USER/REPO format
        row: DataFrame row containing existing repository data
        all_repos_df: Complete DataFrame for duplicate checking
        column_indices: Column index mapping
        existing_lt_repos: Set of existing repos in labeling tool
        row_number: Row number for logging
        
    Returns:
        Dictionary with evaluation results
    """
    start_time = time.time()
    row_info = f" (Row {row_number})" if row_number else ""
    
    # Determine which checks are missing
    missing_checks = determine_missing_checks(row, column_indices)
    
    print(f"\n=== Resume evaluation for {user_repo}{row_info} at {datetime.now().strftime('%H:%M:%S')} ===")
    print(f"[Resume] Missing checks: {[k for k, v in missing_checks.items() if v]}")
    
    # Get evaluation settings for the target language
    eval_settings = get_language_evaluation_settings(TARGET_LANGUAGE)
    target_language = get_language_target_language(TARGET_LANGUAGE)
    
    results = {
        'repo': user_repo, 'should_add': False, 'reason': "",
        'language_name': "N/A", 'language_percent': 0, 'star_count': 0, 
        'loc_count': "N/A", 'manual_review': False,
    }
    
    # Pre-populate results with existing data
    majority_lang_col = f"col_{column_indices['majority_language']}"
    percentage_col = f"col_{column_indices['percentage']}"
    stars_col = f"col_{column_indices['stars']}"
    loc_col = f"col_{column_indices['loc']}"
    
    if majority_lang_col in row.index and not pd.isna(row[majority_lang_col]) and str(row[majority_lang_col]).strip():
        results['language_name'] = str(row[majority_lang_col]).strip()
    
    if percentage_col in row.index and not pd.isna(row[percentage_col]) and str(row[percentage_col]).strip():
        try:
            results['language_percent'] = float(row[percentage_col])
        except ValueError:
            pass
    
    if stars_col in row.index and not pd.isna(row[stars_col]) and str(row[stars_col]).strip():
        try:
            results['star_count'] = int(row[stars_col])
        except ValueError:
            pass
    
    if loc_col in row.index and not pd.isna(row[loc_col]) and str(row[loc_col]).strip():
        results['loc_count'] = str(row[loc_col]).strip()
    
    # Note: We no longer check "already_exists" status - we process all repos
    # Repositories in LT will be processed for data collection
    # Duplicates will be handled by deletion logic in main()
    
    # 3. Perform language and stars check if missing
    if missing_checks['language_check'] or missing_checks['stars_check']:
        details = get_repo_details(user_repo)
        if not details:
            results['reason'] = 'Could not fetch repo details from GitHub API.'
            print(f"=== Resume evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
            return results
        
        if missing_checks['language_check']:
            # Language check - Always output majority language and its percentage
            languages_data = details['languages_data']
            total_bytes = sum(languages_data.values())
            if total_bytes == 0:
                results['reason'] = 'Repo appears to be empty (no code).'
                print(f"=== Resume evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
                return results
            
            language_percentages = {lang: (bytes / total_bytes) * 100 for lang, bytes in languages_data.items()}
            
            # Combine language variations
            language_percentages = combine_js_ts_languages(language_percentages)
            language_percentages = combine_c_cpp_languages(language_percentages)
            
            # Get the majority language (which might be combined JS/TS)
            primary_lang_name, primary_lang_percent = max(language_percentages.items(), key=lambda x: x[1])
            
            # Check if the primary language matches our target language (for evaluation purposes)
            target_lang_percent = language_percentages.get(target_language, 0)
            
            # Always output the majority language and its percentage
            results.update({
                'language_name': primary_lang_name,
                'language_percent': primary_lang_percent / 100,  # Store as decimal
            })
            
            # Store both percentages for evaluation logic
            results['_primary_lang_percent'] = primary_lang_percent
            results['_target_lang_percent'] = target_lang_percent
        
        if missing_checks['stars_check']:
            # Star rating check
            stars = details['repo_data'].get('stargazers_count', 0)
            results['star_count'] = stars
    
    # 4. Perform LOC check if missing
    if missing_checks['loc_check']:
        print(f"[LOC Check] Running LOC check for {user_repo}{row_info}")
        lines = get_lines_count(user_repo)
        
        if lines is None:
            results['loc_count'] = "ERROR"
        elif lines == 0:
            results['loc_count'] = "ERROR 0"
        else:
            results['loc_count'] = lines
    
    # 5. Perform logical check if missing
    if missing_checks['logical_check']:
        # Get current values for evaluation
        primary_lang_percent = results.get('_primary_lang_percent', results['language_percent'] * 100 if isinstance(results['language_percent'], float) else 0)
        target_lang_percent = results.get('_target_lang_percent', 0)
        current_stars = results['star_count']
        current_loc = results['loc_count']
        
        # Determine if LOC check passed
        loc_check_passed = False
        if isinstance(current_loc, int) and current_loc > 0:
            try:
                primary_lang_eval_settings = get_language_evaluation_settings(results['language_name'])
                required_loc = get_required_loc_for_stars(current_stars, primary_lang_eval_settings['loc_thresholds'])
                loc_check_passed = current_loc >= required_loc
            except KeyError:
                # For unconfigured languages, use target language settings as fallback
                print(f"[Resume] Language '{results['language_name']}' not configured, using target language settings")
                required_loc = get_required_loc_for_stars(current_stars, eval_settings['loc_thresholds'])
                loc_check_passed = current_loc >= required_loc
        elif str(current_loc).upper().startswith("ERROR"):
            # Manual review for LOC errors
            results['manual_review'] = True
        
        # Final evaluation logic
        try:
            primary_lang_eval_settings = get_language_evaluation_settings(results['language_name'])
        except KeyError:
            primary_lang_eval_settings = eval_settings
        
        primary_lang_checks_passed = [
            primary_lang_percent >= primary_lang_eval_settings['min_percentage'],
            current_stars >= primary_lang_eval_settings['min_stars'],
            loc_check_passed
        ]
        
        target_lang_checks_passed = [
            target_lang_percent >= eval_settings['min_percentage'],
            current_stars >= eval_settings['min_stars'],
            loc_check_passed
        ]
        
        results['should_add'] = all(primary_lang_checks_passed) or all(target_lang_checks_passed)
        
        if results['manual_review']:
            results['reason'] = "LOC check error – manual review required"
        elif not results['should_add']:
            reasons = []
            if target_lang_percent < eval_settings['min_percentage'] and primary_lang_percent < primary_lang_eval_settings['min_percentage']:
                reasons.append(f"Language percentage too low (Target: {target_lang_percent:.2f}%, Primary: {primary_lang_percent:.2f}%)")
            if current_stars < eval_settings['min_stars'] and current_stars < primary_lang_eval_settings['min_stars']:
                reasons.append(f"Stars < {current_stars}")
            if not loc_check_passed and isinstance(current_loc, int):
                target_required_loc = get_required_loc_for_stars(current_stars, eval_settings['loc_thresholds'])
                primary_required_loc = get_required_loc_for_stars(current_stars, primary_lang_eval_settings['loc_thresholds'])
                required_loc = min(target_required_loc, primary_required_loc)
                reasons.append(f"LOC < {required_loc:,}")
            results['reason'] = ", ".join(reasons)
        else:
            if all(primary_lang_checks_passed) and not all(target_lang_checks_passed):
                results['reason'] = f"Passed criteria for primary language ({results['language_name']})"
            elif all(target_lang_checks_passed) and not all(primary_lang_checks_passed):
                results['reason'] = f"Passed criteria for target language ({target_language})"
            else:
                results['reason'] = f"Passed criteria for both {results['language_name']} and {target_language}"
    
    # Clean up temporary storage variables
    results.pop('_primary_lang_percent', None)
    results.pop('_target_lang_percent', None)
    
    print(f"=== Resume evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
    return results


def handle_repo_movement(user_repo: str, majority_language: str, current_sheet: str) -> bool:
    """
    Handle repository movement based on majority language.
    
    Args:
        user_repo: Repository name in USER/REPO format
        majority_language: The majority language detected for this repo
        current_sheet: Current sheet name where the repo is located
        
    Returns:
        True if repo was moved or deleted, False if no action taken
    """
    target_sheet = get_destination_sheet_for_language(majority_language)
    
    # If the repo should stay in the current sheet, no action needed
    if target_sheet == current_sheet:
        return False
    
    # Check if this is an unconfigured language being moved to Scrap
    try:
        get_language_sheet_name(majority_language)
        language_status = "configured"
    except (KeyError, FileNotFoundError):
        language_status = "unconfigured"
        
    print(f"\n[Movement] Repository {user_repo} has majority language {majority_language}")
    print(f"[Movement] Should move from {current_sheet} to {target_sheet}")
    
    if target_sheet == "Scrap" and language_status == "unconfigured":
        print(colored(f"[Movement] ⚠️  Moving to Scrap sheet - language '{majority_language}' not configured in language_configs.json", "yellow"))
    
    try:
        # Get Google Sheets client and spreadsheet
        client = get_gspread_client()
        spreadsheet = get_google_sheet(client)
        
        # Process the movement
        moved = process_single_repo_movement(client, spreadsheet, current_sheet, user_repo, majority_language)
        
        if moved:
            print(f"[Movement] Successfully processed {user_repo} movement")
            return True
        else:
            print(f"[Movement] No action taken for {user_repo}")
            return False
            
    except Exception as e:
        print(f"[Movement] Error processing movement for {user_repo}: {e}")
        return False


# --- Main Execution ---

def main():
    """
    Main script to process a list of repos from a Google Sheet and evaluate them.
    Now includes dynamic repository movement based on actual language detection.
    """
    print("--- Starting Repository Evaluation ---")
    print(f"Target Language: {TARGET_LANGUAGE}")
    
    # 0. Display column configuration
    print_column_configuration()
    
    # 1. Fetch existing repos from labeling tool
    existing_lt_repos = fetch_existing_repos_from_lt()
    
    # 2. Fetch the updated list of potential repositories to evaluate
    try:
        print(f"\n=== Step 2: Fetching Updated Repository List ===")
        print(f"Fetching potential repos from sheet: {SPREADSHEET_KEY} (Tab: {SHEET_NAME})")
        potential_repos_df, header = fetch_sheet_data(
            CREDS_JSON_PATH,
            SPREADSHEET_KEY,
            SCOPE,
            sheet_name=SHEET_NAME
        )
        print(f"Found {len(potential_repos_df)} total rows to check.")
    except gspread.exceptions.SpreadsheetNotFound:
        print(colored(f"Error: Spreadsheet not found. Make sure the key '{SPREADSHEET_KEY}' is correct and you have shared the sheet with the service account email.", "red"))
        return
    except Exception as e:
        print(colored(f"Error fetching potential repos sheet: {e}", "red"))
        return

    # 3. Get column indices from header
    column_indices = get_column_indices(header)
    print(f"Column mapping: {column_indices}")

    # 4. Update sheet with labeling tool data
    print("\n=== Step 4: Updating Labeling Tool Data ===")
    update_data_from_LT(CREDS_JSON_PATH, SPREADSHEET_KEY, SCOPE, SHEET_NAME, column_indices)

    # 5. Identify and delete duplicate repositories
    print("\n=== Step 5: Identifying Duplicates for Deletion ===")
    duplicate_indices = identify_duplicates_for_deletion(potential_repos_df, column_indices, existing_lt_repos)

    if duplicate_indices:
        print(f"\n=== Step 6: Deleting {len(duplicate_indices)} Duplicate Rows ===")
        try:
            client = _get_gspread_client(CREDS_JSON_PATH, SCOPE)
            sheet = client.open_by_key(SPREADSHEET_KEY).worksheet(SHEET_NAME)
            
            # Sort indices in descending order to avoid shifting issues
            duplicate_indices.sort(reverse=True)
            
            for idx in duplicate_indices:
                sheet_row = idx + 2  # Convert to sheet row number (0-based index + 1 for header + 1 for 1-based)
                try:
                    sheet.delete_rows(sheet_row)
                    print(f"  ❌ Deleted duplicate row {sheet_row}")
                except Exception as e:
                    print(f"  ⚠️ Failed to delete row {sheet_row}: {e}")
            
            print(colored(f"Successfully deleted {len(duplicate_indices)} duplicate rows from the sheet.", "blue"))
            
            # Refresh the DataFrame after deletions
            print("\n=== Refreshing Data After Deletions ===")
            potential_repos_df, header = fetch_sheet_data(
                CREDS_JSON_PATH,
                SPREADSHEET_KEY,
                SCOPE,
                sheet_name=SHEET_NAME
            )
            print(f"Refreshed data: {len(potential_repos_df)} rows remaining")
            
        except Exception as e:
            print(colored(f"Error deleting duplicate rows: {e}", "red"))
    else:
        print("No duplicates found to delete.")

    # 7. Resume Logic: Find rows that need processing
    # A row needs processing if 'Logical Checks' column is empty and URL is not empty.
    unprocessed_rows = []
    user_repo_col_idx = column_indices['user_repo']
    repo_url_col_idx = column_indices['repo_url']
    logical_checks_col_idx = column_indices['logical_checks']

    if len(potential_repos_df.columns) > max(user_repo_col_idx, repo_url_col_idx, logical_checks_col_idx):
        for index, row in potential_repos_df.iterrows():
            user_repo_val = row.iloc[user_repo_col_idx] if user_repo_col_idx < len(row) else ''
            logical_check_val = row.iloc[logical_checks_col_idx] if logical_checks_col_idx < len(row) else ''

            user_repo_present = isinstance(user_repo_val, str) and '/' in user_repo_val.strip()
            logical_check_empty = pd.isna(logical_check_val) or str(logical_check_val).strip() == ''
            
            if user_repo_present and logical_check_empty:
                unprocessed_rows.append((index, row)) # Keep original index and data
    else:
        print(colored(f"Error: Not enough columns in the sheet to find required columns.", "red"))
        return
        
    print(f"Found {len(unprocessed_rows)} unprocessed repositories to evaluate.")

    # 8. Loop through and evaluate each unprocessed repository
    print("\n--- Evaluation Results ---")
    for index, row in unprocessed_rows:
        user_repo = row.iloc[column_indices['user_repo']].strip()
        repo_url = row.iloc[column_indices['repo_url']]
        row_number = index + 2  # +2 because index is 0-based and we skip header row

        try:
            if '/' in user_repo:
                # Use the resume-aware evaluation that only performs missing checks
                result = evaluate_repo_with_resume(user_repo, row, potential_repos_df, column_indices, existing_lt_repos, row_number)
                
                # Write results back to the sheet first (to preserve language data)
                update_sheet_with_results(
                    CREDS_JSON_PATH,
                    SPREADSHEET_KEY,
                    SCOPE,
                    SHEET_NAME,
                    repo_url,
                    result,
                    column_indices,
                )
                
                # Check if repo should be moved to a different sheet based on majority language
                if result['language_name'] != "N/A":
                    repo_moved = handle_repo_movement(user_repo, result['language_name'], SHEET_NAME)
                    if repo_moved:
                        print(colored(f"🔄 MOVED:     {result['repo']} (Row {row_number})", "cyan"), f"- Moved to {get_destination_sheet_for_language(result['language_name'])} sheet")
                        continue  # Skip further processing since repo was moved
                
                # Print to console
                if result['should_add']:
                    print(colored(f"✔ ADD:       {result['repo']} (Row {row_number})", "green"), f"- {result['reason']}")
                else:
                    print(colored(f"✖ DON'T ADD: {result['repo']} (Row {row_number})", "yellow"), f"- {result['reason']}")
            else:
                print(colored(f"✖ SKIPPING:  Row {row_number}", "red"), f"- Malformed user/repo from Column A: '{user_repo}'")

        except Exception as e:
            print(colored(f"✖ ERROR:     {repo_url} (Row {row_number})", "red"), f"- {str(e)}")

    print("\n--- Evaluation Complete ---")
    
    # Summary of movements to Scrap sheet
    print("\n=== Movement Summary ===")
    print("Repositories with unconfigured languages are automatically moved to the 'Scrap' sheet.")
    print("Currently configured languages in language_configs.json:")
    try:
        from config_utils import get_all_language_configs
        all_languages = get_all_language_configs()
        configured_languages = list(all_languages.keys())
        print(f"  - {', '.join(configured_languages)}")
    except Exception as e:
        print(f"  - Error loading language configs: {e}")
    print("Any language not in this list will be moved to the 'Scrap' sheet.")


if __name__ == "__main__":
	main()
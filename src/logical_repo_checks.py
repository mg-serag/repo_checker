#!/home/amir/.venv_base/bin/python3

import requests
from requests.exceptions import RequestException
from termcolor import colored
import webbrowser
import sys
import json
import os
import random
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import time
from datetime import datetime
import concurrent.futures

# --- Script Configuration ---
CREDS_JSON_PATH = os.path.join(os.path.dirname(__file__), 'creds.json')
SCOPE = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
SPREADSHEET_KEY = '1XMbstebCi1xFSwJ7cTN-DXv4jFmdH2owWBE3R7YsXK0'

# --- Language Configuration ---
# Set the target language for evaluation
TARGET_LANGUAGE = 'Go'  # Options: 'Java', 'JavaScript', 'Python', 'Go'

# Language-specific configurations
LANGUAGE_CONFIG = {
    'Java': {
        'sheet_name': 'Java',
        'target_language': 'Java',
        'min_percentage': 70,
        'min_stars': 400,
        'project_id': 42,  # Java project ID in labeling tool
        'loc_thresholds': {
            400: 150000,   # 400 stars -> 150k LOC
            450: 120000,   # 450 stars -> 120k LOC
            500: 100000,   # 500 stars -> 100k LOC
            800: 75000,    # 800 stars -> 75k LOC
            1500: 60000,   # 1500 stars -> 60k LOC
        }
    },
    'JavaScript': {
        'sheet_name': 'JS/TS',
        'target_language': 'JavaScript',
        'min_percentage': 70,
        'min_stars': 400,
        'project_id': 41,  # JS project ID in labeling tool
        'loc_thresholds': {
            400: 150000,
            450: 120000,
            500: 100000,
            800: 75000,
            1500: 60000,
        }
    },
    'Python': {
        'sheet_name': 'Python',
        'target_language': 'Python',
        'min_percentage': 70,
        'min_stars': 400,
        'project_id': 40,  # Python project ID in labeling tool
        'loc_thresholds': {
            400: 150000,
            450: 120000,
            500: 100000,
            800: 75000,
            1500: 60000,
        }
    },
    'Go': {
        'sheet_name': 'Go',
        'target_language': 'Go',
        'min_percentage': 70,
        'min_stars': 400,
        'project_id': 43,  # Go project ID in labeling tool
        'loc_thresholds': {
            400: 150000,
            450: 120000,
            500: 100000,
            800: 75000,
            1500: 60000,
        }
    }
}

# Get current language configuration
LANG_CONFIG = LANGUAGE_CONFIG.get(TARGET_LANGUAGE, LANGUAGE_CONFIG['Java'])
SHEET_NAME = LANG_CONFIG['sheet_name']

# --- Labeling Tool Configuration ---
LT_TOKEN = "YOUR_LT_TOKEN"

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

# --- Config & Token Management ---

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def load_token_string():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Config file not found at {CONFIG_PATH}. Please create it with your GitHub tokens.")
    with open(CONFIG_PATH, "r", encoding="utf-8") as cfg:
        data = json.load(cfg)
    token_str = data.get("GITHUB_TOKENS", "").strip()
    if not token_str:
        raise ValueError("'GITHUB_TOKENS' is missing or empty in config.json")
    return token_str

# --- Token Management & API Request Handling ---

class TokenManager:
    """A class to manage and rotate a list of API tokens."""
    def __init__(self, tokens_str):
        if not tokens_str or not tokens_str.strip():
            raise ValueError("Token string cannot be empty.")
        self.tokens = tokens_str.split()
        self.current_index = 0

    def get_next_token(self):
        """Gets the current token and rotates the index to the next one."""
        token = self.tokens[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.tokens)
        return token

    def get_current_index(self):
        """Returns the current index, for checking if we've looped through all tokens."""
        return self.current_index

# Initialize the token manager with your tokens
TOKEN_STRING = load_token_string()
token_manager = TokenManager(TOKEN_STRING)


def make_github_api_request(url):
    """
    Makes a resilient request to the GitHub API, handling token rotation and rate limiting.
    """
    start_index = token_manager.get_current_index()
    while True:
        token = token_manager.get_next_token()
        headers = {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {token}"}
        
        try:
            response = requests.get(url, headers=headers)
            # Raise an exception for bad status codes (4xx or 5xx), which we handle below
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403 and 'rate limit exceeded' in e.response.text.lower():
                print(colored(f"Rate limit exceeded for token ending in ...{token[-4:]}.", "magenta"))
                
                # Check if we have tried all available tokens
                if token_manager.get_current_index() == start_index:
                    # We have cycled through all tokens and they are all limited. Time to wait.
                    reset_time_utc = int(e.response.headers.get('X-RateLimit-Reset', time.time() + 3600))
                    wait_time = max(reset_time_utc - time.time(), 0) + 5  # Add a 5-second buffer
                    print(colored(f"All tokens are rate-limited. Waiting for {int(wait_time)} seconds until reset...", "red"))
                    time.sleep(wait_time)
                
                # Continue to the next iteration to try the next token
                continue
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
                            gspread.Cell(sheet_row, added_col_idx_1, "YES"),
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
                        gspread.Cell(sheet_row, added_col_idx_1, "NO"),
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

def evaluate_repo(user_repo, all_repos_df, column_indices, existing_lt_repos, row_number=None):
    """
    Evaluates a single repository based on a set of criteria.
    Returns a dictionary with detailed results of each check.
    """
    start_time = time.time()
    row_info = f" (Row {row_number})" if row_number else ""
    print(f"\n=== Starting evaluation for {user_repo}{row_info} at {datetime.now().strftime('%H:%M:%S')} ===")
    print(f"[Config] Target Language: {LANG_CONFIG['target_language']}, Min Stars: {LANG_CONFIG['min_stars']}, Min Percentage: {LANG_CONFIG['min_percentage']}%")
    
    results = {
        'repo': user_repo, 'should_add': False, 'reason': "",
        'language_name': "N/A", 'language_percent': 0, 'star_count': 0, 
        'loc_count': "N/A", 'already_exists': "No", 'manual_review': False,
    }

    # 1. Check if it already exists in the labeling tool
    if user_repo.lower() in existing_lt_repos:
        results['reason'] = "Exists in Labeling Tool"
        results['already_exists'] = "Yes"
        print(f"=== Evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
        return results

    # 2. Check if it already exists in the sheet as a processed repo (marked as 'Yes' in Added column)
    repo_url_col_name = f"col_{column_indices['repo_url']}"
    added_col_name = f"col_{column_indices['added']}"
    
    # Ensure columns exist before filtering
    if repo_url_col_name in all_repos_df.columns and added_col_name in all_repos_df.columns:
        repo_url_lower = f"https://github.com/{user_repo}".lower()
        
        # Normalize URLs in the DataFrame for comparison
        normalized_urls = all_repos_df[repo_url_col_name].str.lower().str.strip()

        # Find matching rows and check if any are marked as 'Yes'
        matching_rows = all_repos_df[normalized_urls == repo_url_lower]
        if not matching_rows.empty:
            # Check if any matching rows are already marked as 'Yes' in the added column
            if matching_rows[added_col_name].str.lower().eq('yes').any():
                results['reason'] = "Exists in Sheet"
                results['already_exists'] = "Yes"
                print(f"=== Evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
                return results

    # 3. Fetch repo details (language and stars)
    details = get_repo_details(user_repo)
    if not details:
        results['reason'] = 'Could not fetch repo details from GitHub API.'
        print(f"=== Evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
        return results

    # 4. Language check (target language >= min_percentage%)
    languages_data = details['languages_data']
    total_bytes = sum(languages_data.values())
    if total_bytes == 0:
        results['reason'] = 'Repo appears to be empty (no code).'
        print(f"=== Evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
        return results
        
    language_percentages = {lang: (bytes / total_bytes) * 100 for lang, bytes in languages_data.items()}
    primary_lang_name, primary_lang_percent = max(language_percentages.items(), key=lambda x: x[1])
    
    # Check if the primary language matches our target language
    target_lang_percent = language_percentages.get(LANG_CONFIG['target_language'], 0)
    
    results.update({
        'language_name': primary_lang_name,
        'language_percent': target_lang_percent / 100,  # Store as decimal
    })
    
    # 5. Star rating check (>= min_stars)
    stars = details['repo_data'].get('stargazers_count', 0)
    results['star_count'] = stars

    # 6. Conditional LOC Check
    # Only run LOC check if language and stars checks have passed
    lines = None
    if target_lang_percent >= LANG_CONFIG['min_percentage'] and stars >= LANG_CONFIG['min_stars']:
        print(f"[LOC Check] Running LOC check for {user_repo}{row_info} (Language: {target_lang_percent:.2f}%, Stars: {stars})")
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
            required_loc = get_required_loc_for_stars(stars, LANG_CONFIG['loc_thresholds'])
            if lines >= required_loc:
                loc_check_passed = True
            else:
                loc_check_passed = False
    else:
        loc_check_passed = False
        if target_lang_percent < LANG_CONFIG['min_percentage']:
            print(f"[LOC Check] Skipping LOC check for {user_repo}{row_info} (Language: {target_lang_percent:.2f}% < {LANG_CONFIG['min_percentage']}%)")
        if stars < LANG_CONFIG['min_stars']:
            print(f"[LOC Check] Skipping LOC check for {user_repo}{row_info} (Stars: {stars} < {LANG_CONFIG['min_stars']})")

    # Manual review determination: other checks pass but LOC had an error
    if (results['already_exists'] == "No" and
        target_lang_percent >= LANG_CONFIG['min_percentage'] and
        stars >= LANG_CONFIG['min_stars'] and
        str(results['loc_count']).upper().startswith("ERROR")):
        results['manual_review'] = True

    # Final verdict
    checks_passed = [
        results['already_exists'] == "No",
        target_lang_percent >= LANG_CONFIG['min_percentage'],
        stars >= LANG_CONFIG['min_stars'],
        loc_check_passed
    ]
    results['should_add'] = all(checks_passed)
    
    if results['manual_review']:
        results['reason'] = "LOC check error – manual review required"
    elif not results['should_add']:
        reasons = []
        if results['already_exists'] == "Yes": reasons.append("Exists in Labeling Tool/Sheet")
        if target_lang_percent < LANG_CONFIG['min_percentage']: 
            reasons.append(f"{LANG_CONFIG['target_language']} < {target_lang_percent:.2f}%")
        if stars < LANG_CONFIG['min_stars']: 
            reasons.append(f"Stars < {stars}")
        if not loc_check_passed and lines is not None:
            required_loc = get_required_loc_for_stars(stars, LANG_CONFIG['loc_thresholds'])
            reasons.append(f"LOC < {required_loc:,}")
        results['reason'] = ", ".join(reasons)
    else:
        results['reason'] = "All checks passed."

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
            gspread.Cell(row_index, column_indices['already_exists'] + 1, results['already_exists']),
            gspread.Cell(row_index, column_indices['logical_checks'] + 1, final_verdict),
        ]
        
        sheet.update_cells(cell_updates, value_input_option='USER_ENTERED')
        print(colored(f"Successfully updated sheet for {results['repo']}.", "blue"))

    except Exception as e:
        print(colored(f"Failed to update sheet for {results['repo']}: {e}", "red"))

# --- Duplicate Detection ---

def preprocess_duplicates(df, column_indices, existing_lt_repos):
    """
    Preprocesses the DataFrame to identify and mark duplicate repositories.
    Marks all instances except the first occurrence as duplicates.
    Also checks against existing repos in the labeling tool.
    """
    print("--- Preprocessing Duplicates ---")
    
    repo_url_col_idx = column_indices['repo_url']
    already_exists_col_idx = column_indices['already_exists']
    logical_checks_col_idx = column_indices['logical_checks']
    user_repo_col_idx = column_indices['user_repo']
    
    repo_url_col_name = f"col_{repo_url_col_idx}"
    already_exists_col_name = f"col_{already_exists_col_idx}"
    logical_checks_col_name = f"col_{logical_checks_col_idx}"
    user_repo_col_name = f"col_{user_repo_col_idx}"
    
    # Ensure we have enough columns
    if len(df.columns) <= max(repo_url_col_idx, already_exists_col_idx, logical_checks_col_idx, user_repo_col_idx):
        print(colored("Warning: Not enough columns to perform duplicate preprocessing", "yellow"))
        return df
    
    # Get all repository URLs and normalize them
    df_copy = df.copy()
    normalized_urls = df_copy[repo_url_col_name].str.lower().str.strip()
    
    # Find duplicates within the sheet
    duplicate_mask = normalized_urls.duplicated(keep='first')  # Keep first occurrence, mark rest as duplicates
    # Exclude blank/empty URLs from being considered duplicates
    duplicate_mask &= normalized_urls != ""
    duplicate_count = duplicate_mask.sum()
    
    # Check against labeling tool existing repos
    lt_duplicate_count = 0
    for idx, row in df_copy.iterrows():
        user_repo_val = row.iloc[user_repo_col_idx] if user_repo_col_idx < len(row) else ''
        if isinstance(user_repo_val, str) and '/' in user_repo_val.strip():
            user_repo_clean = user_repo_val.strip().lower()
            if user_repo_clean in existing_lt_repos:
                df_copy.loc[idx, already_exists_col_name] = "Yes"
                df_copy.loc[idx, logical_checks_col_name] = "No"
                lt_duplicate_count += 1
                print(f"  Found in labeling tool: {user_repo_val}")
    
    if duplicate_count > 0:
        print(f"Found {duplicate_count} duplicate repositories within the sheet")
        
        # Mark duplicates in the DataFrame
        df_copy.loc[duplicate_mask, already_exists_col_name] = "Yes"
        df_copy.loc[duplicate_mask, logical_checks_col_name] = "No"
        
        # Print duplicate information
        duplicate_urls = normalized_urls[duplicate_mask].unique()
        for url in duplicate_urls:
            if pd.notna(url) and url.strip():
                matching_indices = normalized_urls[normalized_urls == url].index.tolist()
                first_row = matching_indices[0] + 2  # Convert to sheet row number
                duplicate_rows = [idx + 2 for idx in matching_indices[1:]]  # Convert to sheet row numbers
                print(f"  Duplicate found: {url}")
                print(f"    First occurrence: Row {first_row}")
                print(f"    Duplicates marked: Rows {duplicate_rows}")
    
    if lt_duplicate_count > 0:
        print(f"Found {lt_duplicate_count} repositories that already exist in labeling tool")
    
    total_duplicates = duplicate_count + lt_duplicate_count
    if total_duplicates == 0:
        print("No duplicates found")
    
    return df_copy

def print_column_configuration():
    """
    Prints the current column configuration for easy reference.
    """
    print("=" * 80)
    print("COLUMN CONFIGURATION")
    print("=" * 80)
    print(f"Sheet: {SPREADSHEET_KEY}")
    print(f"Tab: {SHEET_NAME}")
    print(f"Target Language: {LANG_CONFIG['target_language']}")
    print(f"Min Stars: {LANG_CONFIG['min_stars']}")
    print(f"Min Language Percentage: {LANG_CONFIG['min_percentage']}%")
    print(f"Labeling Tool Project ID: {LANG_CONFIG['project_id']}")
    print("-" * 80)
    print("LOC Thresholds:")
    for stars, loc in sorted(LANG_CONFIG['loc_thresholds'].items()):
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

# --- Main Execution ---

def main():
    """
    Main script to process a list of repos from a Google Sheet and evaluate them.
    Only processes rows where the 'Logical Checks' column is empty.
    """
    print("--- Starting Repository Evaluation ---")
    print(f"Target Language: {TARGET_LANGUAGE}")
    
    # 0. Display column configuration
    print_column_configuration()
    
    # 1. Fetch existing repos from labeling tool
    existing_lt_repos = fetch_existing_repos_from_lt()
    
    # 2. Fetch the list of potential repositories to evaluate
    try:
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

    # 4. Update sheet with labeling tool data (NEW STEP)
    print("\n=== Step 4: Updating Labeling Tool Data ===")
    update_data_from_LT(CREDS_JSON_PATH, SPREADSHEET_KEY, SCOPE, SHEET_NAME, column_indices)

    # 5. Preprocess duplicates - mark all duplicate repositories except the first occurrence
    potential_repos_df = preprocess_duplicates(potential_repos_df, column_indices, existing_lt_repos)

    # 6. Update sheet with duplicate markings
    try:
        client = _get_gspread_client(CREDS_JSON_PATH, SCOPE)
        sheet = client.open_by_key(SPREADSHEET_KEY).worksheet(SHEET_NAME)
        
        # Update Already Exists and Logical Checks columns for duplicates
        already_exists_col_idx = column_indices['already_exists'] + 1  # +1 for 1-based indexing
        logical_checks_col_idx = column_indices['logical_checks'] + 1  # +1 for 1-based indexing
        
        already_exists_col_name = f"col_{column_indices['already_exists']}"
        logical_checks_col_name = f"col_{column_indices['logical_checks']}"
        
        # Find rows that were marked as duplicates
        duplicate_rows = potential_repos_df[
            (potential_repos_df[already_exists_col_name] == "Yes") & 
            (potential_repos_df[logical_checks_col_name] == "No")
        ]
        
        if not duplicate_rows.empty:
            print(f"Updating {len(duplicate_rows)} duplicate rows in the sheet...")
            cell_updates = []
            
            for idx, row in duplicate_rows.iterrows():
                sheet_row = idx + 2  # Convert to sheet row number (0-based index + 1 for header + 1 for 1-based)
                cell_updates.extend([
                    gspread.Cell(sheet_row, already_exists_col_idx, "Yes"),
                    gspread.Cell(sheet_row, logical_checks_col_idx, "No")
                ])
            
            # Batch update for efficiency
            if cell_updates:
                sheet.update_cells(cell_updates, value_input_option='USER_ENTERED')
                print(colored(f"Successfully marked {len(duplicate_rows)} duplicates in the sheet.", "blue"))
        
    except Exception as e:
        print(colored(f"Error updating sheet with duplicate markings: {e}", "red"))

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
                result = evaluate_repo(user_repo, potential_repos_df, column_indices, existing_lt_repos, row_number)
                
                # Print to console
                if result['should_add']:
                    print(colored(f"✔ ADD:       {result['repo']} (Row {row_number})", "green"), f"- {result['reason']}")
                else:
                    print(colored(f"✖ DON'T ADD: {result['repo']} (Row {row_number})", "yellow"), f"- {result['reason']}")

                # Write results back to the sheet
                update_sheet_with_results(
                    CREDS_JSON_PATH,
                    SPREADSHEET_KEY,
                    SCOPE,
                    SHEET_NAME,
                    repo_url,
                    result,
                    column_indices,
                )
            else:
                print(colored(f"✖ SKIPPING:  Row {row_number}", "red"), f"- Malformed user/repo from Column A: '{user_repo}'")

        except Exception as e:
            print(colored(f"✖ ERROR:     {repo_url} (Row {row_number})", "red"), f"- {str(e)}")

    print("\n--- Evaluation Complete ---")


if __name__ == "__main__":
	main()
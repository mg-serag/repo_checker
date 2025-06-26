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
from oauth2client.service_account import ServiceAccountCredentials
from urllib.parse import urlparse
import time
from datetime import datetime
import concurrent.futures

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

# --- Google Sheets Helper ---

def fetch_sheet_data(json_path, spreadsheet_key, scope, sheet_name=None, column_letter=None):
    """
    Fetches data from a Google Sheet. Can fetch a specific column by letter or the entire sheet.
    """
    creds = ServiceAccountCredentials.from_json_keyfile_name(json_path, scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(spreadsheet_key)

    if sheet_name:
        sheet = spreadsheet.worksheet(sheet_name)
    else:
        sheet = spreadsheet.sheet1  # Default to the first sheet

    if column_letter:
        col_index = ord(column_letter.upper()) - ord('A') + 1
        column_values = sheet.col_values(col_index)[1:]  # Get values, skip header
        df = pd.DataFrame(column_values, columns=[f'col_{col_index}'])
    else:
        # Get all values without using headers
        all_values = sheet.get_all_values()
        if not all_values:
            return pd.DataFrame()
        
        # Convert to DataFrame with generic column names
        df = pd.DataFrame(all_values[1:], columns=[f'col_{i}' for i in range(len(all_values[0]))])
    
    return df

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

def evaluate_repo(user_repo, swe_bench_urls, row_number=None):
    """
    Evaluates a single repository based on a set of criteria.
    Returns a dictionary with detailed results of each check.
    
    Criteria:
    - Language: Any language >= 70%
    - Stars: >= 400
    - LOC: Dynamic requirement based on stars (checked only if language and stars pass)
    """
    start_time = time.time()
    row_info = f" (Row {row_number})" if row_number else ""
    print(f"\n=== Starting evaluation for {user_repo}{row_info} at {datetime.now().strftime('%H:%M:%S')} ===")
    
    results = {
        'repo': user_repo, 'should_add': False, 'reason': "",
        'language_name': "N/A", 'language_percent': 0, 'star_count': 0, 
        'loc_count': "N/A", 'exists_in_swe_bench': "Yes",  # Changed default back to "N/A"
        'major_language': "N/A", 'language_check': "N/A", 'stars_check': "N/A", 
        'loc_check': "N/A", 'swe_bench_check': "N/A",
    }

    # 1. Check if it already exists in SWE Bench
    repo_url = f"https://github.com/{user_repo}".lower()
    if repo_url in swe_bench_urls:
        results['reason'] = "Exists in SWE Bench"
        print(f"=== Evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
        return results

    results['swe_bench_check'] = "Pass"
    results['exists_in_swe_bench'] = "No"

    # 2. Fetch repo details (language and stars)
    details = get_repo_details(user_repo)
    if not details:
        results['reason'] = 'Could not fetch repo details from GitHub API.'
        print(f"=== Evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
        return results

    # 3. Language check (any language >= 70%)
    languages_data = details['languages_data']
    total_bytes = sum(languages_data.values())
    if total_bytes == 0:
        results['reason'] = 'Repo appears to be empty (no code).'
        print(f"=== Evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
        return results
        
    language_percentages = {lang: (bytes / total_bytes) * 100 for lang, bytes in languages_data.items()}
    primary_lang_name, primary_lang_percent = max(language_percentages.items(), key=lambda x: x[1])
    
    results.update({
        'language_name': primary_lang_name,
        'language_percent': f"{primary_lang_percent:.2f}",
        'major_language': f"{primary_lang_name} ({primary_lang_percent:.2f}%)"
    })

    if primary_lang_percent >= 70:
        results['language_check'] = "Pass"
    else:
        results['language_check'] = f"Fail ({primary_lang_percent:.2f}%)"
    
    # 4. Star rating check (>= 400)
    stars = details['repo_data'].get('stargazers_count', 0)
    results['star_count'] = stars
    results['stars_check'] = f"Pass ({stars})" if stars >= 400 else f"Fail ({stars})"

    # 5. Conditional LOC Check
    # Only run LOC check if language and stars checks have passed
    if primary_lang_percent >= 70 and stars >= 400:
        print(f"[LOC Check] Running LOC check for {user_repo}{row_info} (Language: {primary_lang_percent:.2f}%, Stars: {stars})")
        lines = get_lines_count(user_repo)
        
        # Handle LOC results
        if lines is None:
            results['loc_count'] = "ERROR"
            results['loc_check'] = "Fail (API Error)"
        elif lines == 0:
            results['loc_count'] = "ERROR 0"
            results['loc_check'] = "Fail (Returned 0)"
        else:
            results['loc_count'] = lines
            base_loc = 100000
            required_loc = max(0, base_loc - (stars * 200))
            if lines >= required_loc:
                results['loc_check'] = f"Pass ({lines:,} >= {required_loc:,})"
            else:
                results['loc_check'] = f"Fail ({lines:,} < {required_loc:,})"
    else:
        results['loc_count'] = "N/A"  # Changed from "ERROR" to "N/A" for skipped checks
        results['loc_check'] = "Skipped"
        if primary_lang_percent < 70:
            print(f"[LOC Check] Skipping LOC check for {user_repo}{row_info} (Language: {primary_lang_percent:.2f}% < 70%)")
        if stars < 400:
            print(f"[LOC Check] Skipping LOC check for {user_repo}{row_info} (Stars: {stars} < 400)")

    # Final verdict
    checks_passed = [
        results['swe_bench_check'] == "Pass",
        results['language_check'] == "Pass",
        "Pass" in results['stars_check'],
        "Pass" in results['loc_check']
    ]
    results['should_add'] = all(checks_passed)
    
    if not results['should_add']:
        reasons = []
        if "Fail" in results['swe_bench_check']: reasons.append("Exists in SWE Bench")
        if "Fail" in results['language_check']: reasons.append("Language < 70%")
        if "Fail" in results['stars_check']: reasons.append("Stars < 400")
        if "Fail" in results['loc_check']:
            if "Skipped" not in results['loc_check']:
                 base_loc = 100000
                 required_loc = max(0, base_loc - (stars * 200))
                 reasons.append(f"LOC < {required_loc:,}")
            else:
                reasons.append("LOC check skipped")
        results['reason'] = ", ".join(reasons)
    else:
        results['reason'] = "All checks passed."

    print(f"=== Evaluation completed in {time.time() - start_time:.2f} seconds ===\n")
    return results

# --- Google Sheets Output ---

def update_sheet_with_results(json_path, spreadsheet_key, scope, sheet_name, repo_url, results):
    """
    Updates a single row in the Google Sheet with the evaluation results.
    If LOC count is 0, it will not be updated to allow for a re-check.
    """
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(json_path, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)

        url_column_index = ord('C') - ord('A') + 1
        url_column_values = sheet.col_values(url_column_index)
        
        try:
            row_index = url_column_values.index(repo_url) + 1
        except ValueError:
            print(colored(f"Could not find URL {repo_url} in the sheet to update.", "red"))
            return

        final_verdict = "Yes" if results['should_add'] else "No"
        
        cell_updates = [
            gspread.Cell(row_index, 5, final_verdict),   # Column E
            gspread.Cell(row_index, 12, results['language_name']),
            gspread.Cell(row_index, 13, results['language_percent']),
            gspread.Cell(row_index, 14, results['star_count']),
            gspread.Cell(row_index, 16, results['exists_in_swe_bench']),
        ]
        
        # Conditionally update LOC cell. If it's 0, skip the update.
        if results['loc_count'] != 0:
            cell_updates.append(gspread.Cell(row_index, 15, str(results['loc_count'])))
        
        sheet.update_cells(cell_updates, value_input_option='USER_ENTERED')
        print(colored(f"Successfully updated sheet for {results['repo']}.", "blue"))

    except Exception as e:
        print(colored(f"Failed to update sheet for {results['repo']}: {e}", "red"))

# --- Main Execution ---

def main():
    """
    Main script to process a list of repos from a Google Sheet and evaluate them.
    Only processes rows where Column L (Language Percentage) is empty.
    """
    # --- Configuration ---
    CREDS_JSON_PATH = 'repo_evaluator/creds.json'
    SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

    # Config for the sheet containing repos that are already in SWE Bench
    SWE_BENCH_SHEET_KEY = '1XMbstebCi1xFSwJ7cTN-DXv4jFmdH2owWBE3R7YsXK0'
    SWE_BENCH_SHEET_NAME = 'JS/TS'
    SWE_BENCH_COLUMN_LETTER = 'C'

    # Config for the sheet containing potential repos to evaluate
    POTENTIAL_REPOS_SHEET_KEY = "1yRoHc_y5cn_IsvYdRG8bxSPONpuXEDRJ_XCdfxkbmgY"
    POTENTIAL_REPOS_SHEET_NAME = 'Trainers repositories'
    POTENTIAL_REPOS_COLUMN_LETTER = 'C'

    print("--- Starting Repository Evaluation ---")
    
    # 1. Fetch the list of repositories already in SWE Bench
    try:
        print(f"Fetching existing SWE Bench repos from sheet: {SWE_BENCH_SHEET_KEY}")
        swe_bench_df = fetch_sheet_data(
            CREDS_JSON_PATH,
            SWE_BENCH_SHEET_KEY,
            SCOPE,
            sheet_name=SWE_BENCH_SHEET_NAME,
            column_letter=SWE_BENCH_COLUMN_LETTER
        )
        swe_bench_urls = swe_bench_df['col_3'].str.lower().str.replace(":/github", "://github").tolist()
        print(f"Found {len(swe_bench_urls)} existing repos.")
    except Exception as e:
        print(colored(f"Error fetching SWE Bench sheet: {e}", "red"))
        return

    # 2. Fetch the list of potential repositories to evaluate
    try:
        print(f"Fetching potential repos from sheet: {POTENTIAL_REPOS_SHEET_KEY}")
        potential_repos_df = fetch_sheet_data(
            CREDS_JSON_PATH,
            POTENTIAL_REPOS_SHEET_KEY,
            SCOPE,
            sheet_name=POTENTIAL_REPOS_SHEET_NAME
        )
        print(f"Found {len(potential_repos_df)} total rows to check.")
    except gspread.exceptions.SpreadsheetNotFound:
        print(colored(f"Error: Spreadsheet not found. Make sure the key '{POTENTIAL_REPOS_SHEET_KEY}' is correct and you have shared the sheet with the service account email.", "red"))
        return
    except Exception as e:
        print(colored(f"Error fetching potential repos sheet: {e}", "red"))
        return

    # --- Resume Logic: Find rows that need processing ---
    # A row needs processing if Column L (index 11) is empty and Column C (URL) is not empty.
    unprocessed_rows = []
    if len(potential_repos_df.columns) >= 13:
        for index, row in potential_repos_df.iterrows():
            # URL present check (Column C -> col_2)
            col2_val = row.get('col_2', '')
            url_present = isinstance(col2_val, str) and col2_val.strip().startswith('http')

            # Column M (language percentage) empty check – treat NaN or empty string as empty
            col12_val = row.get('col_12', '')
            lang_percent_empty = pd.isna(col12_val) or str(col12_val).strip() == ''
            
            if url_present and lang_percent_empty:
                unprocessed_rows.append((index, row)) # Keep original index and data
    else:
        print(colored("Error: Sheet must have at least 13 columns (A-M) to check for unprocessed rows.", "red"))
        return
        
    print(f"Found {len(unprocessed_rows)} unprocessed repositories to evaluate.")

    # 3. Loop through and evaluate each unprocessed repository
    print("\n--- Evaluation Results ---")
    for index, row in unprocessed_rows:
        repo_url = row['col_2']
        row_number = index + 2  # +2 because index is 0-based and we skip header row

        try:
            # Robustly parse the URL to get the 'user/repo' part
            path = urlparse(repo_url).path
            parts = path.strip('/').split('/')
            
            if len(parts) >= 2 and parts[-2] and parts[-1]:
                user_repo = f"{parts[-2]}/{parts[-1]}"
                result = evaluate_repo(user_repo, swe_bench_urls, row_number)
                
                # Print to console
                if result['should_add']:
                    print(colored(f"✔ ADD:       {result['repo']} (Row {row_number})", "green"), f"- {result['reason']}")
                else:
                    print(colored(f"✖ DON'T ADD: {result['repo']} (Row {row_number})", "yellow"), f"- {result['reason']}")

                # Write results back to the sheet
                update_sheet_with_results(
                    CREDS_JSON_PATH,
                    POTENTIAL_REPOS_SHEET_KEY,
                    SCOPE,
                    POTENTIAL_REPOS_SHEET_NAME,
                    repo_url,
                    result,
                )
            else:
                print(colored(f"✖ SKIPPING:  {repo_url} (Row {row_number})", "red"), f"- Malformed URL, could not extract user/repo.")

        except Exception as e:
            print(colored(f"✖ ERROR:     {repo_url} (Row {row_number})", "red"), f"- {str(e)}")

    print("\n--- Evaluation Complete ---")


if __name__ == "__main__":
	main()
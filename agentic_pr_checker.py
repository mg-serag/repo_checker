import os
import sys
import time
import json
import re
import csv
from datetime import datetime
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from termcolor import colored

# --- Configuration ---
load_dotenv()

# Load token from env or config
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as cfg:
            data = json.load(cfg)
        token_str = data.get("GITHUB_TOKENS", "").strip()
        # Use the first token in the list if present
        if token_str:
            GITHUB_TOKEN = token_str.split()[0]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CREDS_JSON_PATH = 'repo_evaluator\creds.json'
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

# --- Script Behavior ---
DEBUG_MODE = False
DEBUG_REPO_URL = "https://github.com/keras-team/keras"
TARGET_GOOD_PRS = 2
LLM_MODEL = "o3-mini"
MERGED_AFTER_DATE = datetime.fromisoformat('2024-11-01T00:00:00+00:00')

# --- Spreadsheet Configuration ---
# Key for the "Trainers repositories" sheet from get_information.py
SPREADSHEET_KEY = "1yRoHc_y5cn_IsvYdRG8bxSPONpuXEDRJ_XCdfxkbmgY"
SHEET_NAME = "Trainers repositories"
# Columns are specified by letter (updated mapping)
REPO_URL_COLUMN = "C"
LOGICAL_CHECK_COLUMN = "E"  # Yes/No after logical checks
TOTAL_PRS_COUNT_COLUMN = "F"  # Total PRs
RELEVANT_PRS_COUNT_COLUMN = "G"  # Logically relevant PRs count
AGENTIC_CHECK_COLUMN = "H"  # Good PRs > 2

# --- Agent Prompt ---
AGENT_PROMPT = """
You are a senior software engineer evaluating a GitHub issue to determine if it's suitable for a "Good PR".

A "Good PR" is linked to an issue that meets these criteria:
1.  **Clear and Actionable**: It describes a specific, actionable problem or feature, providing enough context for a developer to start working.
2.  **Not a Revert**: The issue must not be a request to simply revert previous changes or roll back to an older version.
3.  **Not a Question or Vague Request**: It must not be a simple user question, a vague request for help, or a request for documentation.

Analyze the following issue body and determine if it represents a "Good PR" or a "Bad PR" based on these criteria.

---
{issue_body}
---

Respond with a JSON object containing two keys:
1. "result": A string, either "Good PR" or "Bad PR".
2. "comment": A brief explanation for your decision.
"""

if not GITHUB_TOKEN:
    print("⚠️ Warning: GITHUB_TOKEN environment variable not set. Rate limits will be lower.")
if not OPENAI_API_KEY:
    print("❌ Error: OPENAI_API_KEY environment variable not set. The script cannot run without it.")
    sys.exit(1)

# --- Google Sheets Helper ---
def get_sheet_data(spreadsheet_key, sheet_name):
    """Fetches all data from the Google Sheet and returns it as a pandas DataFrame without headers."""
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_JSON_PATH, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)
        data = sheet.get_all_values()
        return pd.DataFrame(data)
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"❌ Spreadsheet not found. Make sure the key '{spreadsheet_key}' is correct.")
        return None
    except Exception as e:
        print(f"❌ Error fetching sheet data: {e}")
        return None

def update_sheet_cell(spreadsheet_key, sheet_name, row_index, col_letter, value):
    """Updates a single cell in the Google Sheet using a column letter."""
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_JSON_PATH, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)
        col_index = ord(col_letter.upper()) - ord('A') + 1
        sheet.update_cell(row_index, col_index, str(value))
        print(f"📄 Updated sheet: Row {row_index}, Column '{col_letter}' = {value}")
    except Exception as e:
        print(f"❌ Failed to update sheet: {e}")

# --- GitHub API Helpers ---
HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "Agentic-PR-Checker",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

def make_github_api_request(url, params=None, is_retry=False):
    try:
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403 and 'rate limit exceeded' in e.response.text.lower() and not is_retry:
            reset_time_utc = int(e.response.headers.get('X-RateLimit-Reset', time.time() + 60))
            wait_time = max(reset_time_utc - time.time(), 0) + 5  # Add a 5-second buffer
            print(f"⏳ Rate limit exceeded. Waiting for {int(wait_time)} seconds...")
            time.sleep(wait_time)
            return make_github_api_request(url, params, is_retry=True) # Retry the request once
        
        if e.response.status_code == 404:
            print(f"❌ 404 Not Found for URL: {url}")
        else:
            print(f"❌ HTTP Error for {url}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error making request to {url}: {e}")
        return None

def parse_github_url(url):
    try:
        path = urlparse(url).path.strip('/')
        parts = path.split('/')
        if len(parts) >= 2 and parts[0] and parts[1]:
            return parts[0], parts[1]
        return None, None
    except Exception as e:
        print(f"❌ Invalid GitHub URL '{url}': {e}")
        return None, None

def get_merged_prs(owner, repo, merged_after_date):
    print(f"📡 Fetching merged PRs for {owner}/{repo}...")
    prs = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        params = {"state": "closed", "sort": "updated", "direction": "desc", "per_page": 100, "page": page}
        response = make_github_api_request(url, params)
        if not response: break
        data = response.json()
        if not data: break
        
        page_had_valid_prs = False
        for pr in data:
            if pr.get("merged_at"):
                merged_at_dt = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
                if merged_at_dt > merged_after_date:
                    prs.append(pr)
                    page_had_valid_prs = True
        
        # If a page has no PRs merged after our date, we can stop.
        if not page_had_valid_prs or len(data) < 100:
            print("Reached last page or PRs older than the cutoff date. Stopping.")
            break
        page += 1
        time.sleep(0.5)
    print(f"✅ Found {len(prs)} merged PRs since {merged_after_date.date()}.")
    return prs

def get_pr_files(pr_files_url):
    response = make_github_api_request(pr_files_url)
    return response.json() if response else []

def get_issue_body(issue_url):
    response = make_github_api_request(issue_url)
    return response.json().get("body", "") if response else ""

# --- Analysis Logic ---
def extract_issue_number(pr_body):
    if not pr_body: return None
    matches = re.findall(r'(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+(?:[a-zA-Z0-9-]+\/[a-zA-Z0-9-]+\s*)?#(\d+)', pr_body, re.IGNORECASE)
    if not matches: matches = re.findall(r'#(\d+)', pr_body)
    unique_issues = set(matches)
    return unique_issues.pop() if len(unique_issues) == 1 else None

def analyze_pr_files(files):
    if not files: return None, "No files found in PR."
    disallowed_ext = {'.c', '.cpp', '.h', '.cs', '.java', '.go', '.rs'}
    py_ext = {'.py'}
    js_ts_ext = {'.js', '.ts', '.jsx', '.tsx'}
    dependency_files = {'package.json', 'yarn.lock', 'requirements.txt', 'pyproject.toml', 'Pipfile'}
    filenames = [f['filename'] for f in files]
    extensions = {os.path.splitext(f)[1].lower() for f in filenames}
    if not extensions.isdisjoint(disallowed_ext): return None, "Disallowed language detected."
    if not extensions.isdisjoint(py_ext) and not extensions.isdisjoint(js_ts_ext): return None, "Mixed Python and JS/TS languages."
    source_files = [f for f in filenames if os.path.basename(f) not in dependency_files]
    if not source_files: return None, "PR is only a dependency update."
    test_files = [f for f in filenames if 'test' in f.lower() or 'spec' in f.lower()]
    non_test_source_files = [f for f in source_files if f not in test_files]
    if not test_files: return None, "No test files found."
    if not non_test_source_files: return None, "No non-test source files found."
    return "Pass", "All file checks passed."

def run_llm_check(issue_body):
    if not issue_body or len(issue_body.strip()) < 50: return "Bad PR", "Issue body is too short."
    client = OpenAI(api_key=OPENAI_API_KEY)
    try:
        prompt = AGENT_PROMPT.format(issue_body=issue_body)
        response = client.chat.completions.create(model=LLM_MODEL, messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
        result = json.loads(response.choices[0].message.content)
        return result.get("result", "Bad PR"), result.get("comment", "LLM response missing comment.")
    except Exception as e:
        print(f"❌ LLM analysis failed: {e}")
        return "Bad PR", f"LLM analysis failed: {e}"

def find_logically_relevant_prs(owner, repo):
    """
    Performs all non-agentic checks to find PRs that are candidates for agentic review.
    """
    print(f"🔍 Finding logically relevant PRs for {owner}/{repo}...")
    all_prs = get_merged_prs(owner, repo, MERGED_AFTER_DATE)
    logically_relevant_prs = []
    for pr in all_prs:
        pr_number = pr.get('number')
        if not pr_number:
            print(f"  - Skip: PR data is missing 'number' key. Data: {pr}")
            continue

        if DEBUG_MODE: 
            print(f"\n--- Analyzing PR #{pr_number} ---")
            # Print the full PR data structure in debug mode as requested
            print(f"  - PR Data Dump: {json.dumps(pr, indent=2)}")

        issue_number = extract_issue_number(pr.get('body'))
        if not issue_number:
            if DEBUG_MODE: print(f"  - Skip: No unique issue found.")
            continue
            
        # FIX: Construct the files_url manually instead of relying on a non-existent key.
        files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
        files = get_pr_files(files_url)
        status, reason = analyze_pr_files(files)
        if status != "Pass":
            if DEBUG_MODE: print(f"  - Skip: {reason}")
            continue
        
        if DEBUG_MODE: print(f"  - Pass: Meets all logical criteria.")
        # Store the issue number with the PR data
        pr_data = pr.copy()
        pr_data['issue_number'] = issue_number
        logically_relevant_prs.append(pr_data)

    print(f"✅ Found {len(logically_relevant_prs)} logically relevant PRs out of {len(all_prs)} total PRs checked.")
    return logically_relevant_prs, len(all_prs)

def run_agentic_check_on_repo(logically_relevant_prs, owner, repo):
    """
    Runs the agentic (LLM) check on a list of logically relevant PRs.
    Stops when the target number of good PRs is found.
    """
    good_prs_found = 0
    if not logically_relevant_prs: return False
    for pr in logically_relevant_prs:
        print(f"\n🤖 Running agentic check on PR #{pr['number']}...")
        # Use the issue number we stored earlier
        issue_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr['issue_number']}"
        issue_body = get_issue_body(issue_url)
        result, comment = run_llm_check(issue_body)
        print(f"  - LLM Result: {result} | Comment: {comment}")
        if result == "Good PR":
            good_prs_found += 1
        if good_prs_found >= TARGET_GOOD_PRS:
            print(f"🎯 Target of {TARGET_GOOD_PRS} good PRs reached.")
            return True
        time.sleep(1)
    return good_prs_found >= TARGET_GOOD_PRS

def write_prs_to_csv(owner, repo, relevant_prs):
    """Writes the list of relevant PRs and their issues to a repo-specific CSV file."""
    output_dir = "repo_evaluator\pr_reports"
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{owner}_{repo}_relevant_prs.csv")
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['pr_number', 'pr_url', 'issue_number', 'issue_url']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for pr in relevant_prs:
            pr_num = pr['number']
            issue_num = pr['issue_number']
            writer.writerow({
                'pr_number': pr_num,
                'pr_url': f"https://github.com/{owner}/{repo}/pull/{pr_num}",
                'issue_number': issue_num,
                'issue_url': f"https://github.com/{owner}/{repo}/issues/{issue_num}"
            })
    print(f"📄 Saved PR report for {owner}/{repo} to {filename}")

# --- Main Script ---
def main():
    print("--- Agentic PR Checker ---")
    if DEBUG_MODE:
        print("🕵️ DEBUG MODE ENABLED 🕵️")
        owner, repo = parse_github_url(DEBUG_REPO_URL)
        if owner and repo:
            relevant_prs, total_count = find_logically_relevant_prs(owner, repo)
            print(f"\nTotal PRs: {total_count}, Relevant PRs: {len(relevant_prs)}")
            passed = run_agentic_check_on_repo(relevant_prs, owner, repo)
            print(f"\nFinal Result for {DEBUG_REPO_URL}: Agentic Check {'Passed' if passed else 'Failed'}")
        return

    print("🚀 Running in Production Mode (using Google Sheets)...")
    sheet_df = get_sheet_data(SPREADSHEET_KEY, SHEET_NAME)
    if sheet_df is None: sys.exit(1)
    
    repo_col_idx = ord(REPO_URL_COLUMN.upper()) - ord('A')
    logic_col_idx = ord(LOGICAL_CHECK_COLUMN.upper()) - ord('A')
    relevant_prs_col_idx = ord(RELEVANT_PRS_COUNT_COLUMN.upper()) - ord('A')

    # --- Resume Logic: Find rows that need processing ---
    # A row needs processing if logical check (Col D) is "Yes" and relevant PRs (Col F) is empty.
    unprocessed_rows = []
    max_cols = len(sheet_df.columns)
    if max_cols > repo_col_idx and max_cols > logic_col_idx and max_cols > relevant_prs_col_idx:
        for index, row in sheet_df.iloc[1:].iterrows(): # Skip header
            repo_url = row.iat[repo_col_idx] if repo_col_idx < len(row) else ''
            logical_check = row.iat[logic_col_idx] if logic_col_idx < len(row) else ''
            relevant_prs_val = row.iat[relevant_prs_col_idx] if relevant_prs_col_idx < len(row) else ''

            # URL present check
            url_present = isinstance(repo_url, str) and repo_url.strip().startswith('http')

            # Logical check passed?
            logic_passed = isinstance(logical_check, str) and logical_check.strip().lower() == 'yes'

            # Agentic check needed if relevant PRs cell is empty or NaN
            agentic_check_needed = pd.isna(relevant_prs_val) or str(relevant_prs_val).strip() == ''

            if url_present and logic_passed and agentic_check_needed:
                unprocessed_rows.append((index + 1, row)) # Use 1-based index for sheet updates
    
    print(f"Found {len(unprocessed_rows)} repositories that passed logical checks and need agentic evaluation.")
    
    for sheet_row_index, row in unprocessed_rows:
        repo_url = row.iat[repo_col_idx]
        print(f"\n{'='*60}\nProcessing Row {sheet_row_index}: {repo_url}\n{'='*60}")
        
        owner, repo = parse_github_url(repo_url)
        if not owner or not repo:
            print("❌ Skipping: Invalid GitHub URL.")
            continue
            
        relevant_prs, total_count = find_logically_relevant_prs(owner, repo)
        update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, TOTAL_PRS_COUNT_COLUMN, total_count)
        update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, RELEVANT_PRS_COUNT_COLUMN, len(relevant_prs))

        if relevant_prs:
            write_prs_to_csv(owner, repo, relevant_prs)
            passed = run_agentic_check_on_repo(relevant_prs, owner, repo)
            update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, AGENTIC_CHECK_COLUMN, "Yes" if passed else "No")
        else:
            print("⏭️ Skipping agentic check: No logically relevant PRs found.")
            update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, AGENTIC_CHECK_COLUMN, "No")
    print("\n🎉 All repositories analyzed.")

def get_prs_for_repo(user_repo):
    start_time = time.time()
    print(f"\n[PR Fetch] Starting PR fetch for {user_repo}...")
    
    try:
        user, repo = user_repo.split('/')
    except ValueError:
        print("Invalid input format. Please use 'user/repo' format.")
        return None
    
    api_url = f"https://api.github.com/repos/{user}/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100"
    
    try:
        response = make_github_api_request(api_url)
        prs = response.json()
        
        elapsed_time = time.time() - start_time
        print(f"[PR Fetch] Found {len(prs)} PRs in {elapsed_time:.2f} seconds")
        
        return prs
    except requests.exceptions.RequestException as e:
        elapsed_time = time.time() - start_time
        print(f"[PR Fetch] Failed after {elapsed_time:.2f} seconds")
        print(colored(f"Could not get PRs for {user_repo} due to API error: {e}", "red"))
        return None

def check_pr_quality(pr):
    start_time = time.time()
    print(f"\n[PR Check] Starting quality check for PR #{pr['number']}...")
    
    # Logical checks
    logical_checks = {
        'has_description': bool(pr.get('body')),
        'has_review': bool(pr.get('review_comments', 0) > 0),
        'has_comments': bool(pr.get('comments', 0) > 0),
        'is_merged': bool(pr.get('merged_at')),
        'has_commits': bool(pr.get('commits', 0) > 0),
        'has_changes': bool(pr.get('additions', 0) + pr.get('deletions', 0) > 0)
    }
    
    elapsed_time = time.time() - start_time
    print(f"[PR Check] Logical checks completed in {elapsed_time:.2f} seconds")
    
    return logical_checks

def evaluate_pr_with_agent(pr_data, repo_name):
    """
    Evaluates a PR using the agent to determine if it's a good candidate for SWE Bench.
    Returns a dictionary with the evaluation results.
    """
    start_time = time.time()
    print(f"\n[Agent] Starting agent evaluation for PR #{pr_data['number']} at {datetime.now().strftime('%H:%M:%S')}")
    
    # Extract PR information
    pr_title = pr_data.get('title', '')
    pr_body = pr_data.get('body', '')
    pr_url = pr_data.get('html_url', '')
    pr_number = pr_data.get('number', '')
    
    # Prepare the prompt for the agent
    prompt = f"""Evaluate this Pull Request for inclusion in SWE Bench:

Repository: {repo_name}
PR #{pr_number}: {pr_title}
URL: {pr_url}

Description:
{pr_body}

Please evaluate this PR based on the following criteria:
1. Does it fix a bug or implement a feature?
2. Is it a self-contained change?
3. Does it have a clear description of the problem and solution?
4. Is it a good candidate for testing an agent's ability to understand and fix code?

Respond with a JSON object containing:
{{
    "should_include": true/false,
    "reason": "detailed explanation",
    "confidence": 0-1,
    "type": "bug_fix/feature_implementation",
    "complexity": "low/medium/high"
}}
"""
    
    try:
        # Call the agent (using a placeholder for now - replace with actual agent call)
        # For now, we'll simulate the agent's response
        agent_response = {
            "should_include": True,
            "reason": "This PR appears to be a well-documented bug fix with clear problem description and solution.",
            "confidence": 0.85,
            "type": "bug_fix",
            "complexity": "medium"
        }
        
        elapsed_time = time.time() - start_time
        print(f"[Agent] Completed evaluation in {elapsed_time:.2f} seconds")
        print(f"[Agent] Decision: {'Include' if agent_response['should_include'] else 'Exclude'} (Confidence: {agent_response['confidence']:.2f})")
        print(f"[Agent] Type: {agent_response['type']}, Complexity: {agent_response['complexity']}")
        print(f"[Agent] Reason: {agent_response['reason']}")
        
        return {
            'should_include': agent_response['should_include'],
            'reason': agent_response['reason'],
            'confidence': agent_response['confidence'],
            'type': agent_response['type'],
            'complexity': agent_response['complexity'],
            'pr_number': pr_number,
            'pr_url': pr_url,
            'pr_title': pr_title
        }
        
    except Exception as e:
        print(f"[Agent] Error during evaluation: {str(e)}")
        return {
            'should_include': False,
            'reason': f"Error during agent evaluation: {str(e)}",
            'confidence': 0.0,
            'type': 'error',
            'complexity': 'unknown',
            'pr_number': pr_number,
            'pr_url': pr_url,
            'pr_title': pr_title
        }

def evaluate_repo_prs(user_repo):
    """
    Evaluates PRs for a repository using both logical checks and agent-based evaluation.
    """
    print(f"\n=== Starting PR evaluation for {user_repo} at {datetime.now().strftime('%H:%M:%S')} ===")
    total_start_time = time.time()
    
    # Get PRs
    prs = get_prs_for_repo(user_repo)
    if not prs:
        return None
    
    good_prs = 0
    total_prs_checked = 0
    total_agent_time = 0
    
    for pr in prs:
        total_prs_checked += 1
        pr_start_time = time.time()
        
        # Logical checks
        logical_checks = check_pr_quality(pr)
        if not all(logical_checks.values()):
            print(f"PR #{pr['number']} failed logical checks")
            continue
        
        # Agent evaluation
        agent_result = evaluate_pr_with_agent(pr, user_repo)
        pr_elapsed_time = time.time() - pr_start_time
        total_agent_time += pr_elapsed_time
        
        if agent_result['should_include']:
            good_prs += 1
            print(f"PR #{pr['number']} passed agent evaluation in {pr_elapsed_time:.2f} seconds")
        
        if good_prs >= 2:
            break
    
    total_elapsed_time = time.time() - total_start_time
    print(f"\n=== PR Evaluation Summary ===")
    print(f"Total PRs checked: {total_prs_checked}")
    print(f"Good PRs found: {good_prs}")
    print(f"Total agent evaluation time: {total_agent_time:.2f} seconds")
    print(f"Total evaluation time: {total_elapsed_time:.2f} seconds")
    print(f"=== Evaluation completed at {datetime.now().strftime('%H:%M:%S')} ===\n")
    
    return {
        'has_good_prs': good_prs >= 2,
        'total_prs_checked': total_prs_checked,
        'good_prs_found': good_prs,
        'total_agent_time': total_agent_time,
        'total_evaluation_time': total_elapsed_time
    }

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Analysis interrupted by user.")
        sys.exit(0) 
import os
import sys
import time
import json
import re
import csv
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

# --- Configuration ---
TARGET_LANGUAGE = "Rust"  # Set target language directly

# --- Script Behavior ---
DEBUG_MODE = False
DEBUG_REPO_URL = "https://github.com/keras-team/keras"
TARGET_GOOD_PRS = 2
LLM_MODEL = "gpt-4o-mini"
MERGED_AFTER_DATE = datetime.fromisoformat('2024-11-01T00:00:00+00:00')

# --- Parallel Processing Configuration ---
ENABLE_PARALLEL_PROCESSING = True
MAX_WORKERS = 4
PR_PROCESSING_THRESHOLD = 1.0

# --- Single Repo Mode Configuration ---
SINGLE_REPO_MODE = False
SINGLE_REPO_URL = "https://github.com/example/example-repo"
SINGLE_REPO_OUTPUT_DIR = "repo_evaluator/pr_reports"

# --- Load Configuration from Centralized Config ---
from config_utils import (
    get_spreadsheet_key, get_github_token, get_openai_api_key,
    get_language_config, get_source_extensions, get_dependency_files,
    get_test_patterns, get_test_directories, get_non_code_extensions,
    get_universal_test_extensions
)

# Load tokens and configuration
SPREADSHEET_KEY = get_spreadsheet_key()
GITHUB_TOKEN = get_github_token()
OPENAI_API_KEY = get_openai_api_key()

if not GITHUB_TOKEN:
    print("❌ Error: GITHUB_TOKEN not set in config.json or environment variable.")
    sys.exit(1)

if not OPENAI_API_KEY:
    print("❌ Error: OPENAI_API_KEY not set in config.json or environment variable.")
    sys.exit(1)

# Load language configuration
SHEET_NAME = get_language_config(TARGET_LANGUAGE)['sheet_name']
LANGUAGE = TARGET_LANGUAGE

# Load file analysis configuration
try:
    NON_CODE_EXT = get_non_code_extensions()
    UNIVERSAL_TEST_EXT = get_universal_test_extensions()
    TEST_DIRECTORIES = get_test_directories()
except (FileNotFoundError, KeyError):
    # Fallback values
    NON_CODE_EXT = {
        '.md', '.markdown', '.txt', '.json', '.yml', '.yaml', '.xml', '.toml', '.ini', '.cfg', '.lock',
        '.html', '.htm', '.css', '.scss', '.sass', '.less', '.svg', '.png', '.jpg', '.jpeg', '.gif',
        '.ico', '.woff', '.woff2', '.ttf', '.eot', '.csv', '.tsv', '.log', '.sql', '.sh', '.bat',
        '.ps1', '.dockerfile', '.gitignore', '.gitattributes', '.editorconfig', '.browserslistrc'
    }
    UNIVERSAL_TEST_EXT = {'.snap', '.spec'}
    TEST_DIRECTORIES = ['/test/', '/tests/', '/spec/']

# Build source extensions set for all languages
ALL_SOURCE_EXT = set()
try:
    all_languages = get_all_language_configs()
    for lang_name in all_languages.keys():
        ALL_SOURCE_EXT.update(get_source_extensions(lang_name))
except (FileNotFoundError, KeyError):
    # Fallback to basic extensions
    ALL_SOURCE_EXT = {'.java', '.js', '.jsx', '.ts', '.tsx', '.py', '.go', '.c', '.cpp', '.cc', '.cxx', '.h', '.hpp', '.hh', '.hxx', '.rs'}

# Google Sheets configuration
CREDS_JSON_PATH = os.path.join(os.path.dirname(__file__), 'creds.json')
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

# --- Agent Prompt ---
AGENT_PROMPT = """
You are a senior software engineer evaluating a GitHub issue to determine if it's suitable for a "Good PR".

A "Good PR" is linked to an issue that meets these criteria:
1.  **Clear and Actionable**: It describes a specific, actionable problem or feature, providing enough context for a developer to start working.
2.  **Not a Revert**: The issue must not be a request to simply revert previous changes or roll back to an older version.
3.  **Single Issue Focus**: The issue should be focused on closing a single, well-defined problem or feature request.
4.  **Primarily in English**: At least 90 percent of the issue content should be written in English.

Analyze the following issue body and determine if it represents a "Good PR" or a "Bad PR" based on these criteria.

---
{issue_body}
---

Respond with a JSON object containing two keys:
1. "result": A string, either "Good PR" or "Bad PR".
2. "comment": A brief explanation for your decision.
"""

# --- Utility Functions ---

def is_english(text):
    """Check if text is primarily in English (>90% ASCII characters)."""
    if not text or not text.strip():
        return True
    
    total_chars = len(text)
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    return (ascii_chars / total_chars) >= 0.9

def _is_test_file(filepath: str, lang_name: str) -> bool:
    """Determine if a path looks like a test file for the given language."""
    path_norm = filepath.replace("\\", "/").lower()
    base = os.path.basename(path_norm)
    
    # Check for universal test file extensions
    ext = os.path.splitext(filepath)[1].lower()
    if ext in UNIVERSAL_TEST_EXT:
        return True
    
    # Check for test directories
    if any(test_dir in path_norm for test_dir in TEST_DIRECTORIES):
        return True
    
    # Check for test patterns in filename
    if any(token in base for token in ("test", "spec")):
        return True
    
    # Language-specific test patterns
    try:
        from config_utils import get_test_patterns
        test_patterns = get_test_patterns(lang_name)
        if any(base.endswith(pattern) or base.startswith(pattern) for pattern in test_patterns):
            return True
    except (FileNotFoundError, KeyError):
        # Fallback patterns
        if lang_name == "Java" and base.endswith("test.java"):
            return True
        if lang_name == "Python" and (base.startswith("test_") or base.endswith("_test.py")):
            return True
        if lang_name in ["JavaScript", "TypeScript"] and any(base.endswith(suffix) for suffix in ['.test.js', '.test.jsx', '.test.ts', '.test.tsx', '.spec.js', '.spec.jsx', '.spec.ts', '.spec.tsx']):
            return True
        if lang_name == "Go" and base.endswith("_test.go"):
            return True
        if lang_name == "C/C++" and any(base.endswith(suffix) for suffix in ['.test.c', '.test.cpp', '.test.cc', '.test.cxx', '_test.c', '_test.cpp', '_test.cc', '_test.cxx']):
            return True
        if lang_name == "Rust" and base.endswith("_test.rs"):
            return True
    
    return False

def get_language_output_dir():
    """Returns the language-specific output directory for PR reports."""
    language_folder_map = {
        'Java': 'Java_pr_reports',
        'JavaScript': 'JavaScript_pr_reports', 
        'TypeScript': 'TypeScript_pr_reports',
        'Python': 'Python_pr_reports',
        'Go': 'Go_pr_reports',
        'C/C++': 'C_Cpp_pr_reports',
        'Rust': 'Rust_pr_reports'
    }
    
    folder_name = language_folder_map.get(TARGET_LANGUAGE, f'{TARGET_LANGUAGE}_pr_reports')
    output_dir = os.path.join("repo_evaluator", folder_name)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def print_language_configuration():
    """Prints the current language configuration for easy reference."""
    print("=" * 80)
    print("LANGUAGE CONFIGURATION")
    print("=" * 80)
    print(f"Target Language: {TARGET_LANGUAGE}")
    print(f"Sheet Name: {SHEET_NAME}")
    print(f"Spreadsheet Key: {SPREADSHEET_KEY}")
    print(f"Output Directory: {get_language_output_dir()}")
    print("-" * 80)
    print(f"Source Extensions: {', '.join(sorted(get_source_extensions(TARGET_LANGUAGE)))}")
    print(f"Dependency Files: {', '.join(sorted(get_dependency_files(TARGET_LANGUAGE)))}")
    print("-" * 80)
    print(f"Universal Test Extensions: {', '.join(sorted(UNIVERSAL_TEST_EXT))}")
    print(f"Non-Code Extensions: {', '.join(sorted(NON_CODE_EXT))}")
    print("-" * 80)
    print("PROCESSING CONFIGURATION")
    print("-" * 80)
    print(f"LLM Model: {LLM_MODEL}")
    print(f"Target Good PRs: {TARGET_GOOD_PRS}")
    print(f"Parallel Processing: {'Enabled' if ENABLE_PARALLEL_PROCESSING else 'Disabled'}")
    print(f"Max Workers: {MAX_WORKERS}")
    print(f"PR Processing Threshold: {PR_PROCESSING_THRESHOLD:.1%}")
    print("=" * 80)
    print()

# --- Google Sheets Functions ---

def get_column_indices(header):
    """Get column indices from header, case-insensitive."""
    header = [h.lower().strip() for h in header]
    
    def find_idx(headers_to_check, default_idx):
        for h in headers_to_check:
            try:
                return header.index(h)
            except ValueError:
                continue
        return default_idx

    return {
        'user_repo': find_idx(['repository'], 0),
        'logical_checks': find_idx(['logical checks'], 8),
        'total_prs': find_idx(['prs count'], 9),
        'relevant_prs': find_idx(['relevant prs count'], 10),
        'agentic_check': find_idx(['good prs > 2'], 11)
    }

def get_sheet_data(spreadsheet_key, sheet_name):
    """Fetches all data and header from the Google Sheet."""
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_JSON_PATH, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)
        data = sheet.get_all_values()
        if not data:
            return pd.DataFrame(), []
        header = data[0]
        df = pd.DataFrame(data[1:], columns=[f'col_{i}' for i in range(len(header))])
        return df, header
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"❌ Spreadsheet not found. Make sure the key '{spreadsheet_key}' is correct.")
        return None, None
    except Exception as e:
        print(f"❌ Error fetching sheet data: {e}")
        return None, None

def update_sheet_cell(spreadsheet_key, sheet_name, row_index, col_index, value):
    """Updates a single cell in the Google Sheet."""
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_JSON_PATH, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)
        sheet.update_cell(row_index, col_index + 1, str(value))
        print(f"📄 Updated sheet: Row {row_index}, Column {col_index + 1} = {value}")
    except Exception as e:
        print(f"❌ Failed to update sheet: {e}")

# --- GitHub API Functions ---

def make_github_api_request(url, params=None, is_retry=False):
    """Make a request to the GitHub API with rate limit handling."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Agentic-PR-Checker",
        "Authorization": f"token {GITHUB_TOKEN}"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403 and 'rate limit exceeded' in e.response.text.lower() and not is_retry:
            reset_time_utc = int(e.response.headers.get('X-RateLimit-Reset', time.time() + 60))
            wait_time = max(reset_time_utc - time.time(), 0) + 5
            print(f"⏳ Rate limit exceeded. Waiting for {int(wait_time)} seconds...")
            time.sleep(wait_time)
            return make_github_api_request(url, params, is_retry=True)
        
        if e.response.status_code == 404:
            print(f"❌ 404 Not Found for URL: {url}")
        else:
            print(f"❌ HTTP Error for {url}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error making request to {url}: {e}")
        return None

def parse_github_url(url):
    """Parse GitHub URL to extract owner and repo."""
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
    """Fetch merged PRs for a repository since a given date."""
    print(f"📡 Fetching merged PRs for {owner}/{repo}...")
    prs = []
    page = 1
    
    while True:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        params = {"state": "closed", "sort": "updated", "direction": "desc", "per_page": 100, "page": page}
        response = make_github_api_request(url, params)
        if not response:
            break
            
        data = response.json()
        if not data:
            break
        
        page_had_valid_prs = False
        for pr in data:
            if pr.get("merged_at"):
                merged_at_dt = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
                if merged_at_dt > merged_after_date:
                    prs.append(pr)
                    page_had_valid_prs = True
        
        if not page_had_valid_prs or len(data) < 100:
            print("Reached last page or PRs older than the cutoff date. Stopping.")
            break
        page += 1
        time.sleep(0.5)
    
    print(f"✅ Found {len(prs)} merged PRs since {merged_after_date.date()}.")
    return prs

def get_pr_files(pr_files_url):
    """Get files changed in a PR."""
    response = make_github_api_request(pr_files_url)
    return response.json() if response else []

def get_issue_body(issue_url):
    """Get the body text of an issue."""
    response = make_github_api_request(issue_url)
    return response.json().get("body", "") if response else ""

# --- Analysis Functions ---

def extract_issue_number(pr_body):
    """Extract issue number from PR body."""
    if not pr_body:
        return None
    matches = re.findall(r'(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+(?:[a-zA-Z0-9-]+\/[a-zA-Z0-9-]+\s*)?#(\d+)', pr_body, re.IGNORECASE)
    if not matches:
        matches = re.findall(r'#(\d+)', pr_body)
    unique_issues = set(matches)
    return unique_issues.pop() if len(unique_issues) == 1 else None

def analyze_pr_files(files):
    """Perform language-aware logical checks on PR file list."""
    if not files:
        return None, "No files found in PR."

    allowed_ext = get_source_extensions(LANGUAGE)
    dependency_files = get_dependency_files(LANGUAGE)
    filenames = [f["filename"] for f in files]

    # Language gate - ensure no files from other code languages exist
    disallowed_ext = ALL_SOURCE_EXT - allowed_ext

    for fn in filenames:
        ext = os.path.splitext(fn)[1].lower()

        # Skip non-code and dependency files
        if ext in NON_CODE_EXT or os.path.basename(fn) in dependency_files:
            continue

        # Check for disallowed language files
        if ext in disallowed_ext:
            return None, f"Disallowed language file detected: {fn}"

        # Unknown extension - assume code and fail
        if ext not in allowed_ext:
            return None, f"Unknown or binary file type not allowed: {fn}"

    # Split into test and non-test source files
    test_files = []
    non_test_source_files = []

    for fn in filenames:
        ext = os.path.splitext(fn)[1].lower()
        if ext not in allowed_ext:
            continue

        if os.path.basename(fn) in dependency_files:
            continue

        if _is_test_file(fn, LANGUAGE):
            test_files.append(fn)
        else:
            non_test_source_files.append(fn)

    if len(test_files) < 2:
        return None, f"Only {len(test_files)} test file(s) found; at least 2 required."

    if len(non_test_source_files) < 2:
        return None, f"Only {len(non_test_source_files)} non-test source file(s) found; at least 2 required."

    return "Pass", f"All {LANGUAGE} file checks passed."

def run_llm_check(issue_body):
    """Run LLM analysis on issue body to determine if it's a good PR."""
    if not issue_body or len(issue_body.strip()) < 50:
        return "Bad PR", "Issue body is too short."
    
    client = OpenAI(api_key=OPENAI_API_KEY)
    try:
        prompt = AGENT_PROMPT.format(issue_body=issue_body)
        response = client.chat.completions.create(
            model=LLM_MODEL, 
            messages=[{"role": "user", "content": prompt}], 
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        return result.get("result", "Bad PR"), result.get("comment", "LLM response missing comment.")
    except Exception as e:
        print(f"❌ LLM analysis failed: {e}")
        return "Bad PR", f"LLM analysis failed: {e}"

def find_logically_relevant_prs(owner, repo):
    """Find PRs that pass all logical checks and are candidates for agentic review."""
    print(f"🔍 Finding logically relevant PRs for {owner}/{repo}...")
    all_prs = get_merged_prs(owner, repo, MERGED_AFTER_DATE)
    logically_relevant_prs = []
    
    for pr in all_prs:
        pr_number = pr.get('number')

        if DEBUG_MODE: 
            print(f"\n--- Analyzing PR #{pr_number} ---")
            print(f"  - PR Data Dump: {json.dumps(pr, indent=2)}")

        # Extract issue number
        issue_number = extract_issue_number(pr.get('body'))
        if not issue_number:
            if DEBUG_MODE:
                print(f"  - Skip: No unique issue found.")
            continue
        
        # Get issue details
        issue_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
        issue_data = make_github_api_request(issue_url)
        if not issue_data:
            if DEBUG_MODE:
                print(f"  - Skip: Could not fetch issue #{issue_number}")
            continue
        
        issue_json = issue_data.json()
        
        # Check if linked item is an issue, not a PR
        if issue_json.get('pull_request'):
            if DEBUG_MODE:
                print(f"  - Skip: Linked item #{issue_number} is a Pull Request, not an Issue.")
            continue
        
        # Language filtering: Issue must be in English
        issue_body = issue_json.get('body', '')
        if not is_english(issue_body):
            if DEBUG_MODE:
                print(f"  - Skip: Issue #{issue_number} statement contains too many non-English characters.")
            continue
        
        # Get PR files for analysis
        files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
        files = get_pr_files(files_url)
        if not files:
            if DEBUG_MODE:
                print(f"  - Skip: No files found in PR #{pr_number}")
            continue
        
        # Count changes in non-test code files
        allowed_ext = get_source_extensions(LANGUAGE)
        dependency_files = get_dependency_files(LANGUAGE)
        
        non_test_code_changes = 0
        for file_info in files:
            filename = file_info.get('filename', '')
            ext = os.path.splitext(filename)[1].lower()
            
            # Skip non-code files and dependency files
            if ext not in allowed_ext or os.path.basename(filename) in dependency_files:
                continue
            
            # Skip test files
            if _is_test_file(filename, LANGUAGE):
                continue
            
            # Count changes
            additions = file_info.get('additions', 0)
            deletions = file_info.get('deletions', 0)
            non_test_code_changes += additions + deletions
        
        # Require minimum 20 lines of changes in non-test code files
        if non_test_code_changes < 20:
            if DEBUG_MODE:
                print(f"  - Skip: PR #{pr_number} has only {non_test_code_changes} lines of changes in non-test code files (minimum 20 required).")
            continue
            
        # Run file analysis checks
        status, reason = analyze_pr_files(files)
        if status != "Pass":
            if DEBUG_MODE:
                print(f"  - Skip: {reason}")
            continue
        
        if DEBUG_MODE:
            print(f"  - Pass: Meets all logical criteria (non-test code changes: {non_test_code_changes} lines).")
        
        # Store the issue number with the PR data
        pr_data = pr.copy()
        pr_data['issue_number'] = issue_number
        pr_data['non_test_code_changes'] = non_test_code_changes
        logically_relevant_prs.append(pr_data)

    print(f"✅ Found {len(logically_relevant_prs)} logically relevant PRs out of {len(all_prs)} total PRs checked.")
    return logically_relevant_prs, len(all_prs)

def run_parallel_agentic_checks(prs_to_check, owner, repo):
    """Run agentic checks on multiple PRs in parallel."""
    agent_decisions = {}
    
    def process_single_pr(pr):
        """Process a single PR with agentic check."""
        pr_number = pr['number']
        try:
            print(f"🤖 Processing PR #{pr_number} (parallel)...")
            
            issue_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr['issue_number']}"
            issue_body = get_issue_body(issue_url)
            
            result, comment = run_llm_check(issue_body)
            print(f"  ✅ PR #{pr_number}: {result} | {comment}")
            
            return pr_number, {"result": result, "comment": comment}
        except Exception as e:
            print(f"  ❌ PR #{pr_number}: Error - {e}")
            return pr_number, {"result": "Bad PR", "comment": f"Error during processing: {e}"}
    
    # Use ThreadPoolExecutor for parallel processing
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_pr = {executor.submit(process_single_pr, pr): pr for pr in prs_to_check}
        
        for future in as_completed(future_to_pr):
            try:
                pr_number, decision = future.result()
                agent_decisions[pr_number] = decision
            except Exception as e:
                pr = future_to_pr[future]
                pr_number = pr['number']
                print(f"❌ Exception for PR #{pr_number}: {e}")
                agent_decisions[pr_number] = {"result": "Bad PR", "comment": f"Exception: {e}"}
    
    print(f"📊 Completed parallel processing of {len(agent_decisions)} PRs")
    return agent_decisions

def run_agentic_check_on_repo(logically_relevant_prs, owner, repo):
    """Run agentic (LLM) checks on logically relevant PRs."""
    if not logically_relevant_prs:
        return False, {}

    # Apply threshold to determine how many PRs to process
    total_prs = len(logically_relevant_prs)
    prs_to_process = int(total_prs * PR_PROCESSING_THRESHOLD)
    
    print(f"📊 Processing {prs_to_process}/{total_prs} PRs (threshold: {PR_PROCESSING_THRESHOLD:.1%})")
    
    prs_to_check = logically_relevant_prs[:prs_to_process]
    good_prs_found = 0
    agent_decisions = {}
    
    if ENABLE_PARALLEL_PROCESSING and len(prs_to_check) > 1:
        print(f"🚀 Using parallel processing with {MAX_WORKERS} workers...")
        agent_decisions = run_parallel_agentic_checks(prs_to_check, owner, repo)
        
        # Count good PRs found
        good_prs_found = sum(1 for decision in agent_decisions.values() 
                           if decision.get('result') == 'Good PR')
        
        if good_prs_found >= TARGET_GOOD_PRS:
            print(f"🎯 Target of {TARGET_GOOD_PRS} good PRs reached.")
    else:
        print("🔄 Using sequential processing...")
        for pr in prs_to_check:
            pr_number = pr['number']
            print(f"\n🤖 Running agentic check on PR #{pr_number}...")
            
            issue_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr['issue_number']}"
            issue_body = get_issue_body(issue_url)
            
            result, comment = run_llm_check(issue_body)
            print(f"  - LLM Result: {result} | Comment: {comment}")
            
            agent_decisions[pr_number] = {"result": result, "comment": comment}
            
            if result == "Good PR":
                good_prs_found += 1
                if good_prs_found >= TARGET_GOOD_PRS:
                    print(f"🎯 Target of {TARGET_GOOD_PRS} good PRs reached.")
                    break
            time.sleep(1)
    
    return good_prs_found >= TARGET_GOOD_PRS, agent_decisions

def write_prs_to_csv(owner, repo, relevant_prs, agent_decisions, output_dir=None):
    """Write relevant PRs and their issues to a CSV file."""
    if output_dir is None:
        if SINGLE_REPO_MODE:
            output_dir = SINGLE_REPO_OUTPUT_DIR
        else:
            output_dir = get_language_output_dir()
    
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{owner}__{repo}_relevant_prs.csv")
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['pr_id', 'pr_url', 'issue_id', 'issue_url', 'non_test_code_changes', 'agent_result', 'agent_comment']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for pr in relevant_prs:
            pr_num = pr['number']
            issue_num = pr['issue_number']
            decision = agent_decisions.get(pr_num, {})
            non_test_code_changes = pr.get('non_test_code_changes', 0)
            
            writer.writerow({
                'pr_id': pr_num,
                'pr_url': f"https://github.com/{owner}/{repo}/pull/{pr_num}",
                'issue_id': issue_num,
                'issue_url': f"https://github.com/{owner}/{repo}/issues/{issue_num}",
                'non_test_code_changes': non_test_code_changes,
                'agent_result': decision.get('result', 'Not Checked'),
                'agent_comment': decision.get('comment', '')
            })
    
    print(f"📄 Saved PR report for {owner}/{repo} to {filename}")

def run_single_repo_analysis(repo_url):
    """Run agentic PR checker on a single repository."""
    print(f"🔍 Running single repo analysis for: {repo_url}")
    
    owner, repo = parse_github_url(repo_url)
    if not owner or not repo:
        print(f"❌ Invalid repository URL: {repo_url}")
        return False
    
    print(f"📊 Processing repository: {owner}/{repo}")
    
    # Find logically relevant PRs
    relevant_prs, total_count = find_logically_relevant_prs(owner, repo)
    print(f"📈 Total PRs found: {total_count}")
    print(f"📈 Logically relevant PRs: {len(relevant_prs)}")
    
    # Run agentic checks
    if relevant_prs:
        passed, agent_decisions = run_agentic_check_on_repo(relevant_prs, owner, repo)
        print(f"🤖 Agentic check result: {'PASSED' if passed else 'FAILED'}")
        
        # Write results to CSV
        write_prs_to_csv(owner, repo, relevant_prs, agent_decisions, get_language_output_dir())
        
        # Print summary
        good_prs = sum(1 for decision in agent_decisions.values() if decision.get('result') == 'Good PR')
        print(f"✅ Good PRs found: {good_prs}")
        print(f"❌ Bad PRs found: {len(agent_decisions) - good_prs}")
        
        return passed
    else:
        print("⏭️ No logically relevant PRs found for agentic analysis.")
        return False

# --- Command Line Argument Parsing ---

def parse_command_line_args():
    """Parse command line arguments for configuration options."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Agentic PR Checker with parallel processing support')
    parser.add_argument('--model', type=str, default=LLM_MODEL,
                       help=f'LLM model to use (default: {LLM_MODEL})')
    parser.add_argument('--target-good-prs', type=int, default=TARGET_GOOD_PRS,
                       help=f'Target number of good PRs to find (default: {TARGET_GOOD_PRS})')
    parser.add_argument('--parallel', action='store_true', default=ENABLE_PARALLEL_PROCESSING,
                       help='Enable parallel processing (default: enabled)')
    parser.add_argument('--no-parallel', action='store_true',
                       help='Disable parallel processing')
    parser.add_argument('--max-workers', type=int, default=MAX_WORKERS,
                       help=f'Maximum number of parallel workers (default: {MAX_WORKERS})')
    parser.add_argument('--threshold', type=float, default=PR_PROCESSING_THRESHOLD,
                       help=f'Threshold for PR processing (0.0-1.0, default: {PR_PROCESSING_THRESHOLD})')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug mode')
    parser.add_argument('--debug-repo', type=str, default=DEBUG_REPO_URL,
                       help=f'Repository URL for debug mode (default: {DEBUG_REPO_URL})')
    
    return parser.parse_args()

def update_config_from_args(args):
    """Update global configuration based on command line arguments."""
    global LLM_MODEL, TARGET_GOOD_PRS, ENABLE_PARALLEL_PROCESSING, MAX_WORKERS, PR_PROCESSING_THRESHOLD, DEBUG_MODE, DEBUG_REPO_URL
    
    LLM_MODEL = args.model
    TARGET_GOOD_PRS = args.target_good_prs
    
    if args.no_parallel:
        ENABLE_PARALLEL_PROCESSING = False
    else:
        ENABLE_PARALLEL_PROCESSING = args.parallel
    
    MAX_WORKERS = args.max_workers
    PR_PROCESSING_THRESHOLD = max(0.0, min(1.0, args.threshold))
    
    if args.debug:
        DEBUG_MODE = True
        DEBUG_REPO_URL = args.debug_repo

# --- Main Function ---

def main():
    """Main function to run the agentic PR checker."""
    print("--- Agentic PR Checker ---")
    
    # Parse command line arguments
    args = parse_command_line_args()
    update_config_from_args(args)
    
    # Display language configuration
    print_language_configuration()
    
    # Check for single repo mode
    if SINGLE_REPO_MODE:
        print("🎯 SINGLE REPO MODE ENABLED")
        print(f"Target Repository: {SINGLE_REPO_URL}")
        print("=" * 60)
        
        success = run_single_repo_analysis(SINGLE_REPO_URL)
        if success:
            print("🎉 Single repo analysis completed successfully!")
        else:
            print("❌ Single repo analysis failed or no good PRs found.")
        return
    
    # Debug mode
    if DEBUG_MODE:
        print("🕵️ DEBUG MODE ENABLED 🕵️")
        owner, repo = parse_github_url(DEBUG_REPO_URL)
        if owner and repo:
            relevant_prs, total_count = find_logically_relevant_prs(owner, repo)
            print(f"\nTotal PRs: {total_count}, Relevant PRs: {len(relevant_prs)}")
            passed, agent_decisions = run_agentic_check_on_repo(relevant_prs, owner, repo)
            print(f"\nFinal Result for {DEBUG_REPO_URL}: Agentic Check {'Passed' if passed else 'Failed'}")
        return

    # Production mode - using Google Sheets
    print("🚀 Running in Production Mode (using Google Sheets)...")
    sheet_df, header = get_sheet_data(SPREADSHEET_KEY, SHEET_NAME)
    if sheet_df is None:
        sys.exit(1)
    
    column_indices = get_column_indices(header)
    print(f"Column mapping: {column_indices}")
    
    user_repo_col_idx = column_indices['user_repo']
    logic_col_idx = column_indices['logical_checks']
    agentic_col_idx = column_indices['agentic_check']

    # Find rows that need processing
    unprocessed_rows = []
    max_cols = len(sheet_df.columns)

    if max_cols > max(user_repo_col_idx, logic_col_idx, agentic_col_idx):
        for index, row in sheet_df.iterrows():
            user_repo = row.iloc[user_repo_col_idx] if user_repo_col_idx < len(row) else ''
            logical_check = row.iloc[logic_col_idx] if logic_col_idx < len(row) else ''
            agentic_val = row.iloc[agentic_col_idx] if agentic_col_idx < len(row) else ''

            user_repo_present = isinstance(user_repo, str) and '/' in user_repo.strip()
            logic_passed = isinstance(logical_check, str) and logical_check.strip() == 'Yes'
            agentic_empty = pd.isna(agentic_val) or str(agentic_val).strip() == ''

            if user_repo_present and logic_passed and agentic_empty:
                unprocessed_rows.append((index + 2, row))
    else:
        print("Error: Not enough columns in the sheet to find required columns.")
        return

    print(f"Found {len(unprocessed_rows)} repositories that passed logical checks and need agentic evaluation.")
    
    # Process each repository
    for sheet_row_index, row in unprocessed_rows:
        user_repo = row.iloc[user_repo_col_idx].strip()
        print(f"\n{'='*60}\nProcessing Row {sheet_row_index}: {user_repo}\n{'='*60}")
        
        try:
            owner, repo = user_repo.split('/')
        except ValueError:
            print(f"❌ Skipping: Invalid user/repo format in Column A: '{user_repo}'")
            continue
            
        relevant_prs, total_count = find_logically_relevant_prs(owner, repo)
        update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, column_indices['total_prs'], total_count)
        update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, column_indices['relevant_prs'], len(relevant_prs))

        if relevant_prs:
            passed, agent_decisions = run_agentic_check_on_repo(relevant_prs, owner, repo)
            write_prs_to_csv(owner, repo, relevant_prs, agent_decisions, get_language_output_dir())
            update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, column_indices['agentic_check'], "Yes" if passed else "No")
        else:
            print("⏭️ Skipping agentic check: No logically relevant PRs found.")
            update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, column_indices['agentic_check'], "No")
    
    print("\n🎉 All repositories analyzed.")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Analysis interrupted by user.")
        sys.exit(0) 
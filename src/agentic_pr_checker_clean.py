"""
Agentic PR Checker

This script analyzes GitHub repositories to find "Good PRs" based on logical and agentic criteria.
PR reports are stored in the /repo_evaluator folder in the base directory (one level up from src).
"""

import os
import sys
import time
import json
import re
import csv
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import requests
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

# --- Configuration ---
TARGET_LANGUAGE = "JavaScript"  # Set target language directly

# --- Script Behavior ---
# Remove DEBUG_MODE and DEBUG_REPO_URL
TARGET_GOOD_PRS = 2
LLM_MODEL = "gpt-4o-mini"
MERGED_AFTER_DATE = datetime.fromisoformat('2024-11-01T00:00:00+00:00')

# --- Parallel Processing Configuration ---
ENABLE_PARALLEL_PROCESSING = True
MAX_WORKERS = 10
PR_PROCESSING_THRESHOLD = 1.0
 

# --- Manual Mode Configuration ---
MANUAL_MODE = False
MANUAL_REPOS = [
    "apache/arrow", "DynamoRIO/dynamorio", "pocoproject/poco", "fluent/fluent-bit", "valkey-io/valkey"
    # "wevm/viem",
    # "renovatebot/renovate",
    # "apache/seatunnel",
    # "checkstyle/checkstyle"
    # "go-gitea__gitea"
]

# Get the base directory for single repo output
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)  # Go up one level from src

# --- Load Configuration from Centralized Config ---
from config_utils import (
    get_spreadsheet_key, get_github_token, get_openai_api_key,
    get_language_config, get_all_language_configs, get_source_extensions, get_dependency_files,
    get_non_code_extensions, get_test_file_patterns, get_language_csv_folder
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
    TEST_FILE_PATTERNS = get_test_file_patterns()
except (FileNotFoundError, KeyError):
    # Fallback values
    NON_CODE_EXT = {
        '.md', '.markdown', '.txt', '.json', '.yml', '.yaml', '.xml', '.toml', '.ini', '.cfg', '.lock',
        '.config', '.conf', '.properties', '.env', '.settings', '.prefs', '.rc', '.pro',
        '.mk', '.make', '.cmake', '.gradle', '.sbt',
        '.html', '.htm', '.css', '.scss', '.sass', '.less', '.svg', '.png', '.jpg', '.jpeg', '.gif',
        '.ico', '.woff', '.woff2', '.ttf', '.eot', '.csv', '.tsv', '.log', '.sql', '.sh', '.bat',
        '.ps1', '.dockerfile', '.gitignore', '.gitattributes', '.editorconfig', '.browserslistrc'
    }
    TEST_FILE_PATTERNS = {
        "file_suffixes": [".test.", ".spec.", "_test.", "_spec."],
        "file_extensions": [".snap"],
        "directory_patterns": ["/test/", "/tests/", "/spec/", "/specs/", "__tests__", "__test__"]
    }

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
In General, the issue should clearly indicate a problem or a bug or a feature request. The issues statment can include a solution or suggestion, but not necessarily.
If the issue statment is just reporting the bug, then that is considered valid.

A "Good PR" is linked to an issue that meets these criteria:
1.  **Clear and Actionable**: It describes a specific problem or feature request, providing enough context for a developer to start working.
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

# --- Progress Tracking ---

class ProgressTracker:
    """Thread-safe progress tracker for parallel processing."""
    
    def __init__(self, total_items, description="Processing"):
        self.total_items = total_items
        self.completed_items = 0
        self.description = description
        self.lock = Lock()
        self.start_time = time.time()
        
    def update(self, increment=1):
        """Update progress by increment."""
        with self.lock:
            self.completed_items += increment
            self._print_progress()
    
    def _print_progress(self):
        """Print current progress."""
        if self.total_items == 0:
            percentage = 100.0
        else:
            percentage = (self.completed_items / self.total_items) * 100
        
        elapsed_time = time.time() - self.start_time
        if self.completed_items > 0:
            estimated_total_time = elapsed_time * (self.total_items / self.completed_items)
            remaining_time = estimated_total_time - elapsed_time
            remaining_str = f" | ETA: {remaining_time:.1f}s"
        else:
            remaining_str = ""
        
        # Create progress bar
        bar_length = 30
        filled_length = int(bar_length * self.completed_items / max(self.total_items, 1))
        bar = '█' * filled_length + '░' * (bar_length - filled_length)
        
        print(f"\r🔄 {self.description}: [{bar}] {self.completed_items}/{self.total_items} ({percentage:.1f}%) | {elapsed_time:.1f}s{remaining_str}", end='', flush=True)
        
        if self.completed_items >= self.total_items:
            print()  # New line when complete

def create_simple_progress_bar(current, total, prefix="Progress", length=30):
    """Create a simple text-based progress bar."""
    if total == 0:
        percentage = 100.0
    else:
        percentage = (current / total) * 100
    
    filled_length = int(length * current / max(total, 1))
    bar = '█' * filled_length + '░' * (length - filled_length)
    
    return f"{prefix}: [{bar}] {current}/{total} ({percentage:.1f}%)"

# --- Utility Functions ---

def is_english(text):
    """Check if text is primarily in English (>90% ASCII characters)."""
    if not text or not text.strip():
        return True
    
    total_chars = len(text)
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    return (ascii_chars / total_chars) >= 0.9

def _is_test_file(filepath: str, lang_name: str) -> bool:
    """Determine if a path looks like a test file using comprehensive patterns."""
    path_norm = filepath.replace("\\", "/").lower()
    filename = os.path.basename(filepath).lower()
    
    # Check for test file suffixes (e.g., .test.js, .spec.py, _test.py)
    for suffix in TEST_FILE_PATTERNS.get("file_suffixes", []):
        if suffix in filename:
            return True
    
    # Check for test file extensions (e.g., .snap)
    ext = os.path.splitext(filepath)[1].lower()
    if ext in TEST_FILE_PATTERNS.get("file_extensions", []):
        return True
    
    # Check for test directory patterns
    for pattern in TEST_FILE_PATTERNS.get("directory_patterns", []):
        if pattern in path_norm:
            return True
    
    return False

def get_language_output_dir():
    """Returns the language-specific output directory for PR reports."""
    # Get the base directory (one level up from src)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)  # Go up one level from src
    
    # Sanitize language name for folder creation
    sanitized_language = TARGET_LANGUAGE.replace('/', '_').replace('#', 'Sharp')
    folder_name = f"{sanitized_language}_pr_reports"
    
    output_dir = os.path.join(base_dir, "repo_evaluator", folder_name)
    
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
    output_dir = get_language_output_dir()
    print(f"Output Directory: {output_dir}")
    print(f"Output Directory (absolute): {os.path.abspath(output_dir)}")
    print("-" * 80)
    print(f"Source Extensions: {', '.join(sorted(get_source_extensions(TARGET_LANGUAGE)))}")
    print(f"Dependency Files: {', '.join(sorted(get_dependency_files(TARGET_LANGUAGE)))}")
    print("-" * 80)
    print(f"Test File Suffixes: {', '.join(TEST_FILE_PATTERNS.get('file_suffixes', []))}")
    print(f"Test File Extensions: {', '.join(TEST_FILE_PATTERNS.get('file_extensions', []))}")
    print(f"Test Directory Patterns: {', '.join(TEST_FILE_PATTERNS.get('directory_patterns', []))}")
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
    print(f"📡 Fetching merged PRs for {owner}/{repo} since {merged_after_date.date()}...")
    prs = []
    page = 1
    total_fetched = 0
    
    while True:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        params = {"state": "closed", "sort": "updated", "direction": "desc", "per_page": 100, "page": page}
        response = make_github_api_request(url, params)
        if not response:
            break
            
        data = response.json()
        if not data:
            break
        
        total_fetched += len(data)
        print(f"   📄 Page {page}: Fetched {len(data)} PRs (total: {total_fetched})", end='', flush=True)
        
        page_had_valid_prs = False
        for pr in data:
            if pr.get("merged_at"):
                merged_at_dt = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
                if merged_at_dt > merged_after_date:
                    prs.append(pr)
                    page_had_valid_prs = True
        
        print(f" → {len(prs)} PRs merged after {merged_after_date.date()} so far")
        
        if not page_had_valid_prs or len(data) < 100:
            print(f"   🏁 Reached last page or PRs older than cutoff date. Stopping at page {page}.")
            break
        page += 1
        time.sleep(0.5)
    
    print(f"✅ Found {len(prs)} merged PRs since {merged_after_date.date()} (from {total_fetched} total PRs checked).")
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

def extract_issue_number(pr_body, pr_number=None):
    """Extract issue number from PR body. Returns issue number only if exactly one unique issue is found.
    
    Returns:
        tuple: (issue_number, rejection_reason) where issue_number is str or None, 
               and rejection_reason is str describing why it was rejected (if applicable)
    """
    if not pr_body:
        return None, "No PR body content"
    
    # First try to find issues with closing keywords
    matches = re.findall(r'(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+(?:[a-zA-Z0-9-]+\/[a-zA-Z0-9-]+\s*)?#(\d+)', pr_body, re.IGNORECASE)
    
    # If no closing keywords found, look for any issue references
    if not matches:
        matches = re.findall(r'#(\d+)', pr_body)
    
    # Only return if exactly one unique issue is found
    unique_issues = set(matches)
    if len(unique_issues) == 1:
        return unique_issues.pop(), None
    elif len(unique_issues) > 1:
        pr_context = f" for PR #{pr_number}" if pr_number else ""
        sorted_issues = sorted(unique_issues)
        rejection_reason = f"Multiple issues found in PR body: {', '.join(['#' + issue for issue in sorted_issues])}"
        print(f"[WARN] Multiple issues found in PR body via regex{pr_context}: {sorted_issues}. Rejecting for single-issue requirement.")
        return None, rejection_reason
    else:
        return None, "No issue references found in PR body"

def analyze_pr_files(files):
    """Perform language-aware logical checks on PR file list."""
    if not files:
        return None, "No files found in PR."

    # Use config_utils to get the language family extensions and non-code extensions
    allowed_ext = get_source_extensions(LANGUAGE)  # This is already a set of all family extensions
    dependency_files = get_dependency_files(LANGUAGE)
    non_code_ext = NON_CODE_EXT
    test_file_extensions = set(TEST_FILE_PATTERNS.get("file_extensions", []))

    filenames = [f["filename"] for f in files]

    for fn in filenames:
        ext = os.path.splitext(fn)[1].lower()

        # Always allow non-code/text/markup files and dependency files
        if ext in non_code_ext or os.path.basename(fn) in dependency_files:
            continue

        # Allow test file extensions (like .snap files)
        if ext in test_file_extensions:
            continue

        # Only allow files with extensions in the language family
        if ext not in allowed_ext:
            return None, f"Disallowed or unknown code file detected: {fn}"

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

    if len(test_files) < 1:
        return None, f"Only {len(test_files)} test file(s) found; at least 1 required."

    if len(non_test_source_files) < 1:
        return None, f"Only {len(non_test_source_files)} non-test source file(s) found; at least 1 required."

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

def get_closing_issue_number(pr_number, owner, repo, pr_body=None):
    """
    Try to get the closing issue number for a PR. First try regex parsing PR body, then GraphQL method.
    
    - Regex (PR body): Only accepts PRs with exactly one unique issue linked
    - GraphQL: Accepts PRs with multiple issues and returns the first one
    
    Returns:
        tuple: (issue_number, rejection_reason) where issue_number is str or None, 
               and rejection_reason is str or None describing why it was rejected
    """
    # First try: Parse PR body with regex (fast and reliable for most cases)
    if pr_body is not None:
        issue_number, rejection_reason = extract_issue_number(pr_body, pr_number)
        if issue_number:
            print(f"[INFO] Found issue #{issue_number} via PR body regex for PR #{pr_number}")
            return issue_number, "regex_success"
        elif rejection_reason:
            return None, rejection_reason
    
    # Second try: GraphQL query for closing issues (like get_relevant_prs_from_repo.py)
    print(f"[INFO] PR body regex failed, trying GraphQL query for PR #{pr_number}")
    try:
        graphql_query = """
        query($owner: String!, $name: String!, $prNumber: Int!) {
            repository(owner: $owner, name: $name) {
                pullRequest(number: $prNumber) {
                    closingIssuesReferences(first: 5) {
                        nodes {
                            number
                        }
                    }
                }
            }
        }
        """
        
        variables = {
            "owner": owner,
            "name": repo,
            "prNumber": pr_number
        }
        
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            "https://api.github.com/graphql",
            json={"query": graphql_query, "variables": variables},
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            if not data.get('errors'):
                pr_data = data.get('data', {}).get('repository', {}).get('pullRequest')
                if pr_data:
                    issue_nodes = pr_data.get('closingIssuesReferences', {}).get('nodes', [])
                    if len(issue_nodes) >= 1:
                        issue_number = str(issue_nodes[0]['number'])
                        if len(issue_nodes) == 1:
                            print(f"[INFO] Found issue #{issue_number} via GraphQL for PR #{pr_number}")
                            return issue_number, "graphql_success"
                        else:
                            all_issues = [str(node['number']) for node in issue_nodes]
                            print(f"[INFO] Found multiple issues via GraphQL for PR #{pr_number}: {all_issues}. Using first one: #{issue_number}")
                            return issue_number, f"graphql_multiple_issues ({', '.join(['#' + issue for issue in all_issues])})"
    except Exception as e:
        print(f"[WARN] GraphQL query failed for PR #{pr_number}: {e}")
    
    # Both methods failed
    print(f"[WARN] Both regex and GraphQL methods failed to find closing issue for PR #{pr_number}")
    return None, "No issue found via regex or GraphQL"

def find_logically_relevant_prs(owner, repo):
    """Find PRs that pass all logical checks and are candidates for agentic review. Always collect detailed rejection reasons and per-PR failure info for reporting."""
    print(f"\n🔍 LOGICAL FILTERING for {owner}/{repo}...")
    all_prs = get_merged_prs(owner, repo, MERGED_AFTER_DATE)
    logically_relevant_prs = []
    rejected_prs = []  # Always collect rejection details
    pr_failure_details = []  # Always collect for CSV

    # Initialize counters for detailed reporting
    filter_stats = {
        'total_prs': len(all_prs),
        'no_issue': 0,
        'multiple_issues': 0,
        'not_english': 0,
        'insufficient_changes': 0,
        'file_checks_failed': 0,
        'passed': 0
    }

    print(f"📈 Starting logical analysis of {len(all_prs)} PRs...")

    for i, pr in enumerate(all_prs, 1):
        pr_number = pr.get('number')
        pr_url = f"https://github.com/{owner}/{repo}/pull/{pr_number}"
        rejection_reason = None
        failed_check = None

        # Show progress every 10 PRs or in debug mode
        if i % 10 == 0 or False: # DEBUG_MODE is removed
            progress_bar = create_simple_progress_bar(i, len(all_prs), "Filtering")
            print(f"\r{progress_bar}", end='', flush=True)

        # Extract issue number
        issue_number, issue_rejection_reason = get_closing_issue_number(pr_number, owner, repo, pr.get('body'))
        if not issue_number:
            # Categorize the rejection reason
            if "Multiple issues found in PR body" in issue_rejection_reason:
                filter_stats['multiple_issues'] += 1
                failed_check = "multiple_issues"
                rejection_reason = issue_rejection_reason
            else:
                filter_stats['no_issue'] += 1
                failed_check = "no_issue" 
                rejection_reason = issue_rejection_reason or "No unique issue found."
            
            rejected_prs.append({'number': pr_number, 'url': pr_url, 'reason': rejection_reason})
            pr_failure_details.append({'pr_number': pr_number, 'pr_url': pr_url, 'failed_check': failed_check, 'reason': rejection_reason})
            continue
        
        # If GraphQL found multiple issues but still returned one, track it for reporting
        if issue_rejection_reason and "graphql_multiple_issues" in issue_rejection_reason:
            print(f"[INFO] PR #{pr_number} has multiple issues detected via GraphQL but proceeding with analysis: {issue_rejection_reason}")
            # Note: We don't increment multiple_issues counter here since we're proceeding with the PR

        # Get issue details
        issue_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
        issue_data = make_github_api_request(issue_url)
        if not issue_data:
            rejection_reason = f"Could not fetch issue #{issue_number}"
            failed_check = "no_issue"
            rejected_prs.append({'number': pr_number, 'url': pr_url, 'reason': rejection_reason})
            pr_failure_details.append({'pr_number': pr_number, 'pr_url': pr_url, 'failed_check': failed_check, 'reason': rejection_reason})
            continue

        issue_json = issue_data.json()

        # Check if linked item is an issue, not a PR
        if issue_json.get('pull_request'):
            rejection_reason = f"Linked item #{issue_number} is a Pull Request, not an Issue."
            failed_check = "no_issue"
            rejected_prs.append({'number': pr_number, 'url': pr_url, 'reason': rejection_reason})
            pr_failure_details.append({'pr_number': pr_number, 'pr_url': pr_url, 'failed_check': failed_check, 'reason': rejection_reason})
            continue

        # Language filtering: Issue must be in English
        issue_body = issue_json.get('body', '')
        if not is_english(issue_body):
            filter_stats['not_english'] += 1
            rejection_reason = f"Issue #{issue_number} statement contains too many non-English characters."
            failed_check = "not_english"
            rejected_prs.append({'number': pr_number, 'url': pr_url, 'reason': rejection_reason})
            pr_failure_details.append({'pr_number': pr_number, 'pr_url': pr_url, 'failed_check': failed_check, 'reason': rejection_reason})
            continue

        # Get PR files for analysis
        files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
        files = get_pr_files(files_url)
        if not files:
            rejection_reason = f"No files found in PR #{pr_number}"
            failed_check = "file_checks"
            rejected_prs.append({'number': pr_number, 'url': pr_url, 'reason': rejection_reason})
            pr_failure_details.append({'pr_number': pr_number, 'pr_url': pr_url, 'failed_check': failed_check, 'reason': rejection_reason})
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
            filter_stats['insufficient_changes'] += 1
            rejection_reason = f"PR #{pr_number} has only {non_test_code_changes} lines of changes in non-test code files (minimum 20 required)."
            failed_check = "insufficient_changes"
            rejected_prs.append({'number': pr_number, 'url': pr_url, 'reason': rejection_reason})
            pr_failure_details.append({'pr_number': pr_number, 'pr_url': pr_url, 'failed_check': failed_check, 'reason': rejection_reason})
            continue

        # Run file analysis checks
        status, reason = analyze_pr_files(files)
        if status != "Pass":
            filter_stats['file_checks_failed'] += 1
            rejection_reason = reason
            failed_check = "file_checks"
            rejected_prs.append({'number': pr_number, 'url': pr_url, 'reason': rejection_reason})
            pr_failure_details.append({'pr_number': pr_number, 'pr_url': pr_url, 'failed_check': failed_check, 'reason': rejection_reason})
            continue

        filter_stats['passed'] += 1
        pr_failure_details.append({'pr_number': pr_number, 'pr_url': pr_url, 'failed_check': 'passed', 'reason': ''})

        # Store the issue number with the PR data
        pr_data = pr.copy()
        pr_data['issue_number'] = issue_number
        pr_data['non_test_code_changes'] = non_test_code_changes
        logically_relevant_prs.append(pr_data)

    # Final progress bar
    progress_bar = create_simple_progress_bar(len(all_prs), len(all_prs), "Filtering")
    print(f"\r{progress_bar}")

    # Detailed filtering summary
    print(f"\n📊 LOGICAL FILTERING RESULTS for {owner}/{repo}:")
    print(f"   📈 Total PRs analyzed: {filter_stats['total_prs']}")
    print(f"   ❌ No linked issue: {filter_stats['no_issue']}")
    print(f"   ❌ Multiple issues linked: {filter_stats['multiple_issues']}")
    print(f"   ❌ Not in English: {filter_stats['not_english']}")
    print(f"   ❌ Insufficient changes: {filter_stats['insufficient_changes']}")
    print(f"   ❌ Failed file checks: {filter_stats['file_checks_failed']}")
    print(f"   ✅ Passed all logical checks: {filter_stats['passed']}")

    success_rate = (filter_stats['passed'] / max(filter_stats['total_prs'], 1)) * 100
    print(f"   📊 Success rate: {success_rate:.1f}%")

    return logically_relevant_prs, len(all_prs), rejected_prs, pr_failure_details


def run_parallel_agentic_checks(prs_to_check, owner, repo):
    """Run agentic checks on multiple PRs in parallel."""
    agent_decisions = {}
    progress_tracker = ProgressTracker(len(prs_to_check), f"🤖 Analyzing PRs for {owner}/{repo}")
    
    print(f"\n🚀 Starting parallel processing of {len(prs_to_check)} PRs with {MAX_WORKERS} workers...")
    
    def process_single_pr(pr):
        """Process a single PR with agentic check."""
        pr_number = pr['number']
        try:
            issue_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr['issue_number']}"
            issue_body = get_issue_body(issue_url)
            
            result, comment = run_llm_check(issue_body)
            
            # Update progress
            progress_tracker.update()
            
            return pr_number, {"result": result, "comment": comment}
        except Exception as e:
            progress_tracker.update()
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
                agent_decisions[pr_number] = {"result": "Bad PR", "comment": f"Exception: {e}"}
    
    # Summary of results
    good_prs = sum(1 for d in agent_decisions.values() if d.get('result') == 'Good PR')
    bad_prs = len(agent_decisions) - good_prs
    
    print(f"\n📊 Parallel processing completed:")
    print(f"   ✅ Good PRs found: {good_prs}")
    print(f"   ❌ Bad PRs found: {bad_prs}")
    print(f"   📈 Total processed: {len(agent_decisions)}")
    
    return agent_decisions

def run_agentic_check_on_repo(logically_relevant_prs, owner, repo):
    """Run agentic (LLM) checks on logically relevant PRs."""
    if not logically_relevant_prs:
        print("⚠️ No logically relevant PRs found for agentic analysis.")
        return False, {}

    # Apply threshold to determine how many PRs to process
    total_prs = len(logically_relevant_prs)
    prs_to_process = int(total_prs * PR_PROCESSING_THRESHOLD)
    
    print(f"\n📊 AGENTIC ANALYSIS PLAN for {owner}/{repo}:")
    print(f"   📈 Total logically relevant PRs: {total_prs}")
    print(f"   🎯 PRs to analyze (threshold {PR_PROCESSING_THRESHOLD:.1%}): {prs_to_process}")
    print(f"   🏆 Target good PRs needed: {TARGET_GOOD_PRS}")
    print(f"   🤖 LLM Model: {LLM_MODEL}")
    
    prs_to_check = logically_relevant_prs[:prs_to_process]
    good_prs_found = 0
    agent_decisions = {}
    
    if ENABLE_PARALLEL_PROCESSING and len(prs_to_check) > 1:
        print(f"\n🚀 Using parallel processing with {MAX_WORKERS} workers...")
        agent_decisions = run_parallel_agentic_checks(prs_to_check, owner, repo)
        
        # Count good PRs found
        good_prs_found = sum(1 for decision in agent_decisions.values() 
                           if decision.get('result') == 'Good PR')
        
        if good_prs_found >= TARGET_GOOD_PRS:
            print(f"🎯 SUCCESS: Target of {TARGET_GOOD_PRS} good PRs reached!")
        else:
            print(f"⚠️ Only found {good_prs_found}/{TARGET_GOOD_PRS} good PRs")
    else:
        print(f"\n🔄 Using sequential processing for {len(prs_to_check)} PRs...")
        
        for i, pr in enumerate(prs_to_check, 1):
            pr_number = pr['number']
            
            # Show progress
            progress_bar = create_simple_progress_bar(i-1, len(prs_to_check), "Progress")
            print(f"\r{progress_bar}", end='', flush=True)
            
            print(f"\n🤖 Analyzing PR #{pr_number} ({i}/{len(prs_to_check)})...")
            
            issue_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr['issue_number']}"
            issue_body = get_issue_body(issue_url)
            
            result, comment = run_llm_check(issue_body)
            print(f"   💡 Result: {result}")
            print(f"   📝 Reason: {comment}")
            
            agent_decisions[pr_number] = {"result": result, "comment": comment}
            
            if result == "Good PR":
                good_prs_found += 1
                print(f"   ✅ Good PRs found so far: {good_prs_found}/{TARGET_GOOD_PRS}")
                if good_prs_found >= TARGET_GOOD_PRS:
                    print(f"\n🎯 SUCCESS: Target of {TARGET_GOOD_PRS} good PRs reached!")
                    break
            
            time.sleep(1)  # Rate limiting
        
        # Final progress bar
        progress_bar = create_simple_progress_bar(len(prs_to_check), len(prs_to_check), "Progress")
        print(f"\r{progress_bar}")
        
        # Sequential summary
        bad_prs = len(agent_decisions) - good_prs_found
        print(f"\n📊 Sequential processing completed:")
        print(f"   ✅ Good PRs found: {good_prs_found}")
        print(f"   ❌ Bad PRs found: {bad_prs}")
        print(f"   📈 Total processed: {len(agent_decisions)}")
    
    return good_prs_found >= TARGET_GOOD_PRS, agent_decisions

def write_prs_to_csv(owner, repo, relevant_prs, agent_decisions, output_dir=None):
    """Write relevant PRs and their issues to a CSV file."""
    if output_dir is None:
        output_dir = get_language_output_dir()
    
    # Ensure the output directory exists
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
    print(f"📁 Output directory: {output_dir}")

def write_logical_check_report_csv(owner, repo, pr_failure_details, output_dir=None):
    """Write a CSV report listing each PR and which logical check it failed (or passed)."""
    if output_dir is None:
        output_dir = get_language_output_dir()

    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{owner}__{repo}_logical_check_report.csv")
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['pr_number', 'pr_url', 'failed_check', 'reason']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in pr_failure_details:
            writer.writerow(row)
    print(f"📄 Saved logical check report for {owner}/{repo} to {filename}")
    print(f"📁 Output directory: {output_dir}")


def run_single_repo_analysis(repo_url):
    """Run agentic PR checker on a single repository. In debug mode, output detailed rejection reasons for each PR. Always output logical check report CSV."""
    print(f"🔍 Running single repo analysis for: {repo_url}")
    
    owner, repo = parse_github_url(repo_url)
    if not owner or not repo:
        print(f"❌ Invalid repository URL: {repo_url}")
        return False
    
    print(f"📊 Processing repository: {owner}/{repo}")

    # Find logically relevant PRs
    relevant_prs, total_count, rejected_prs, pr_failure_details = find_logically_relevant_prs(owner, repo)
    print(f"📈 Total PRs found: {total_count}")
    print(f"📈 Logically relevant PRs: {len(relevant_prs)}")

    # 👉 Write initial CSV with status 'Not Checked'
    write_prs_to_csv(owner, repo, relevant_prs, {}, get_language_output_dir())
    # 👉 Write logical check report CSV
    write_logical_check_report_csv(owner, repo, pr_failure_details, get_language_output_dir())

    # Print detailed rejection report
    print("\n================ DETAILED REJECTION REPORT ================" )
    if rejected_prs:
        for r in rejected_prs:
            print(f"PR #{r['number']} | {r['url']} | Reason: {r['reason']}")
    else:
        print("No PRs were rejected by logical checks.")
    print("==========================================================\n")

    # Run agentic checks
    if relevant_prs:
        passed, agent_decisions = run_agentic_check_on_repo(relevant_prs, owner, repo)
        print(f"🤖 Agentic check result: {'PASSED' if passed else 'FAILED'}")
        
        # 👉 Overwrite CSV with final Good/Bad statuses
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
    parser.add_argument('--debug-repo', type=str, default=None, # DEBUG_REPO_URL is removed
                       help='Repository URL for debug mode (default: None)')
    parser.add_argument('--manual-repos', type=str, default=None,
                       help='Comma-separated list of USER/REPO to process in manual mode')
    return parser.parse_args()

def update_config_from_args(args):
    """Update global configuration based on command line arguments."""
    global LLM_MODEL, TARGET_GOOD_PRS, ENABLE_PARALLEL_PROCESSING, MAX_WORKERS, PR_PROCESSING_THRESHOLD, MANUAL_MODE, MANUAL_REPOS
    
    LLM_MODEL = args.model
    TARGET_GOOD_PRS = args.target_good_prs
    
    if args.no_parallel:
        ENABLE_PARALLEL_PROCESSING = False
    else:
        ENABLE_PARALLEL_PROCESSING = args.parallel
    
    MAX_WORKERS = args.max_workers
    PR_PROCESSING_THRESHOLD = max(0.0, min(1.0, args.threshold))
    
    if args.debug:
        MANUAL_MODE = True
        MANUAL_REPOS = [args.debug_repo]
    if args.manual_repos:
        MANUAL_MODE = True
        MANUAL_REPOS = [repo.strip() for repo in args.manual_repos.split(',') if repo.strip()]

# --- Main Function ---

def main():
    """Main function to run the agentic PR checker."""
    print("--- Agentic PR Checker ---")
    
    # Parse command line arguments
    args = parse_command_line_args()
    update_config_from_args(args)
    
    # Display language configuration
    print_language_configuration()
    
    if MANUAL_MODE:
        print("🎯 MANUAL MODE ENABLED")
        print(f"Target Repositories: {MANUAL_REPOS}")
        print("=" * 60)
        # Load sheet for existence check
        sheet_df, header = get_sheet_data(SPREADSHEET_KEY, SHEET_NAME)
        if sheet_df is not None:
            column_indices = get_column_indices(header)
            user_repo_col_idx = column_indices['user_repo']
            logic_col_idx = column_indices['logical_checks']
            agentic_col_idx = column_indices['agentic_check']
        else:
            column_indices = None
            user_repo_col_idx = logic_col_idx = agentic_col_idx = None
        for repo_str in MANUAL_REPOS:
            print("\n" + "="*80)
            print(f"📦 REPOSITORY: {repo_str}")
            print("="*80)
            try:
                owner, repo = repo_str.split('/')
            except ValueError:
                print(f"❌ Skipping: Invalid user/repo format: '{repo_str}'")
                continue
            # Check if repo exists in sheet
            sheet_row_index = None
            if sheet_df is not None:
                for idx, row in sheet_df.iterrows():
                    user_repo_val = row.iloc[user_repo_col_idx] if user_repo_col_idx < len(row) else ''
                    if isinstance(user_repo_val, str) and user_repo_val.strip().lower() == repo_str.lower():
                        sheet_row_index = idx + 2  # 1-based, plus header
                        break
            # Run analysis and update sheet if present
            relevant_prs, total_count, rejected_prs, pr_failure_details = find_logically_relevant_prs(owner, repo)
            print(f"📈 Total PRs found: {total_count}")
            print(f"📈 Logically relevant PRs: {len(relevant_prs)}")
            write_prs_to_csv(owner, repo, relevant_prs, {}, get_language_output_dir())
            write_logical_check_report_csv(owner, repo, pr_failure_details, get_language_output_dir())
            if sheet_row_index is not None and column_indices is not None:
                update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, column_indices['total_prs'], total_count)
                update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, column_indices['relevant_prs'], len(relevant_prs))
            print("\n================ DETAILED REJECTION REPORT ================" )
            if rejected_prs:
                for r in rejected_prs:
                    print(f"PR #{r['number']} | {r['url']} | Reason: {r['reason']}")
            else:
                print("No PRs were rejected by logical checks.")
            print("==========================================================\n")
            if relevant_prs:
                passed, agent_decisions = run_agentic_check_on_repo(relevant_prs, owner, repo)
                print(f"🤖 Agentic check result: {'PASSED' if passed else 'FAILED'}")
                write_prs_to_csv(owner, repo, relevant_prs, agent_decisions, get_language_output_dir())
                good_prs = sum(1 for decision in agent_decisions.values() if decision.get('result') == 'Good PR')
                print(f"✅ Good PRs found: {good_prs}")
                print(f"❌ Bad PRs found: {len(agent_decisions) - good_prs}")
                if sheet_row_index is not None and column_indices is not None:
                    update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, column_indices['agentic_check'], "Yes" if passed else "No")
            else:
                print("⏭️ No logically relevant PRs found for agentic analysis.")
                if sheet_row_index is not None and column_indices is not None:
                    update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, column_indices['agentic_check'], "No")
        print("\n🎉 All manual repositories analyzed.")
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
            logic_passed = isinstance(logical_check, str) and logical_check.strip().lower() in ('yes', 'manual')
            agentic_empty = pd.isna(agentic_val) or str(agentic_val).strip() == ''

            if user_repo_present and logic_passed and agentic_empty:
                unprocessed_rows.append((index + 2, row))
    else:
        print("Error: Not enough columns in the sheet to find required columns.")
        return

    print(f"Found {len(unprocessed_rows)} repositories that passed logical checks and need agentic evaluation.")
    
    # Process each repository
    print(f"\n🚀 PROCESSING {len(unprocessed_rows)} REPOSITORIES")
    print("=" * 80)
    
    for repo_index, (sheet_row_index, row) in enumerate(unprocessed_rows, 1):
        user_repo = row.iloc[user_repo_col_idx].strip()
        
        print(f"\n{'='*80}")
        print(f"📦 REPOSITORY {repo_index}/{len(unprocessed_rows)}: {user_repo} (Sheet Row {sheet_row_index})")
        print(f"{'='*80}")
        
        try:
            owner, repo = user_repo.split('/')
        except ValueError:
            print(f"❌ Skipping: Invalid user/repo format in Column A: '{user_repo}'")
            continue
            
        # Phase 1: Logical filtering
        relevant_prs, total_count, rejected_prs, pr_failure_details = find_logically_relevant_prs(owner, repo)
        update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, column_indices['total_prs'], total_count)
        update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, column_indices['relevant_prs'], len(relevant_prs))

        # 👉 Write initial CSV with status 'Not Checked'
        write_prs_to_csv(owner, repo, relevant_prs, {}, get_language_output_dir())
        # 👉 Write logical check report CSV
        write_logical_check_report_csv(owner, repo, pr_failure_details, get_language_output_dir())

        # Phase 2: Agentic analysis
        if relevant_prs:
            passed, agent_decisions = run_agentic_check_on_repo(relevant_prs, owner, repo)
            write_prs_to_csv(owner, repo, relevant_prs, agent_decisions, get_language_output_dir())
            update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, column_indices['agentic_check'], "Yes" if passed else "No")
            
            # Final repository summary
            good_prs = sum(1 for d in agent_decisions.values() if d.get('result') == 'Good PR')
            print(f"\n🏁 FINAL RESULT for {user_repo}:")
            print(f"   📊 Total PRs: {total_count}")
            print(f"   ✅ Logically relevant: {len(relevant_prs)}")
            print(f"   🤖 Analyzed by agent: {len(agent_decisions)}")
            print(f"   🏆 Good PRs found: {good_prs}")
            print(f"   🎯 Target met: {'YES' if passed else 'NO'}")
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
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
from dotenv import load_dotenv
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from termcolor import colored

# --- Configuration ---
# load_dotenv()

# --- Language Configuration ---
TARGET_LANGUAGE = "JavaScript"  # Set target language directly

# --- Script Behavior ---
DEBUG_MODE = False
DEBUG_REPO_URL = "https://github.com/keras-team/keras"
TARGET_GOOD_PRS = 2
LLM_MODEL = "gpt-4o-mini"  # Changed to GPT-4o mini
MERGED_AFTER_DATE = datetime.fromisoformat('2024-11-01T00:00:00+00:00')

# --- Parallel Processing Configuration ---
ENABLE_PARALLEL_PROCESSING = True
MAX_WORKERS = 4  # Number of parallel workers for agentic checks
PR_PROCESSING_THRESHOLD = 1.0  # Default 100% - process all PRs that passed logical checks

# --- Single Repo Mode Configuration ---
SINGLE_REPO_MODE = False  # Set to True to run on a specific repo instead of Google Sheets
SINGLE_REPO_URL = "https://github.com/example/example-repo"  # Replace with your target repo
SINGLE_REPO_OUTPUT_DIR = "repo_evaluator/pr_reports"  # Output directory for single repo mode

# --- Spreadsheet Configuration ---
# Key for the sheet to be processed
SPREADSHEET_KEY = "1XMbstebCi1xFSwJ7cTN-DXv4jFmdH2owWBE3R7YsXK0"

# Language-specific configurations for agentic PR checks
LANGUAGE_CONFIG = {
    'Java': {
        'sheet_name': 'Java',
        'target_language': 'Java',
        'source_ext': {'.java'},
        'dependency_files': {
            'pom.xml', 'build.gradle', 'build.gradle.kts',
            'settings.gradle', 'settings.gradle.kts',
            'gradlew', 'gradlew.bat', 'mvnw', 'mvnw.cmd'
        },
    },
    'JavaScript': {
        'sheet_name': 'JS/TS',
        'target_language': 'JavaScript',
        'source_ext': {'.js', '.jsx', '.ts', '.tsx'},
        'dependency_files': {
            'package.json', 'yarn.lock', 'pnpm-lock.yaml', 'package-lock.json',
            'webpack.config.js', 'rollup.config.js', 'vite.config.js',
            'babel.config.js', '.eslintrc.js', '.prettierrc.js'
        },
    },
    'TypeScript': {
        'sheet_name': 'JS/TS',
        'target_language': 'TypeScript',
        'source_ext': {'.ts', '.tsx'},
        'dependency_files': {
            'package.json', 'yarn.lock', 'pnpm-lock.yaml', 'package-lock.json',
            'tsconfig.json', 'tsconfig.build.json', 'webpack.config.js',
            'rollup.config.js', 'vite.config.ts', 'babel.config.js',
            '.eslintrc.js', '.prettierrc.js'
        },
    },
    'Python': {
        'sheet_name': 'Python',
        'target_language': 'Python',
        'source_ext': {'.py'},
        'dependency_files': {
            'requirements.txt', 'pyproject.toml', 'setup.py', 'Pipfile',
            'Pipfile.lock', 'poetry.lock', 'tox.ini', 'pytest.ini'
        },
    },
    'Go': {
        'sheet_name': 'Go',
        'target_language': 'Go',
        'source_ext': {'.go'},
        'dependency_files': {
            'go.mod', 'go.sum', 'Gopkg.toml', 'Gopkg.lock'
        },
    }
}

# Load token from env or config
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as cfg:
                data = json.load(cfg)
            token_str = data.get("GITHUB_TOKENS", "").strip()
            # Use the first token in the list if present
            if token_str:
                GITHUB_TOKEN = token_str.split()[0]
        except (UnicodeDecodeError, json.JSONDecodeError, IOError) as e:
            print(f"⚠️ Warning: Could not read config.json file: {e}")
            print("   Please ensure the file is UTF-8 encoded and contains valid JSON.")
            GITHUB_TOKEN = None

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CREDS_JSON_PATH = os.path.join(os.path.dirname(__file__), 'creds.json')
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

# Get current language configuration
LANG_CONFIG = LANGUAGE_CONFIG.get(TARGET_LANGUAGE, LANGUAGE_CONFIG['JavaScript'])
SHEET_NAME = LANG_CONFIG['sheet_name']
LANGUAGE = LANG_CONFIG['target_language']

# Non-code/text extensions that are always acceptable regardless of LANGUAGE
NON_CODE_EXT = {
    '.md', '.markdown', '.txt', '.json', '.yml', '.yaml', '.xml', '.toml', '.ini', '.cfg', '.lock',
    '.html', '.htm', '.css', '.scss', '.sass', '.less', '.svg', '.png', '.jpg', '.jpeg', '.gif',
    '.ico', '.woff', '.woff2', '.ttf', '.eot', '.csv', '.tsv', '.log', '.sql', '.sh', '.bat',
    '.ps1', '.dockerfile', '.gitignore', '.gitattributes', '.editorconfig', '.browserslistrc'
}

# Universal test file extensions that are always considered test files
UNIVERSAL_TEST_EXT = {'.snap', '.spec'}

# Build one big set with _all_ source extensions so we can identify disallowed ones
# dynamically. This ensures that when LANGUAGE = "Java", any .py or .ts files will
# be flagged automatically without maintaining a bespoke disallowed list.
ALL_SOURCE_EXT = set()
for _lang_cfg in LANGUAGE_CONFIG.values():
    ALL_SOURCE_EXT.update(_lang_cfg["source_ext"])


def is_english(text):
    """
    A more lenient heuristic to check if a string is likely in English.
    Returns True if over 90% of characters are ASCII.
    """
    if not text or not text.strip():
        return True  # Assume empty descriptions are fine
    
    total_chars = len(text)
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    
    # If the proportion of ASCII characters is high, assume it's English
    if (ascii_chars / total_chars) >= 0.9:
        return True
        
    return False


def _get_language_config(lang_name: str):
    """Return config dict for a language, falling back to empty sets if unknown."""
    return LANGUAGE_CONFIG.get(lang_name, {
        "source_ext": set(),
        "dependency_files": set(),
        "sheet_name": "Unknown",
        "target_language": "Unknown"
    })


def _is_test_file(filepath: str, lang_name: str) -> bool:
    """
    Determine if a path looks like a test file for the given language.
    Enhanced to handle universal test patterns and language-specific patterns.
    """
    path_norm = filepath.replace("\\", "/").lower()
    base = os.path.basename(path_norm)
    lang_cfg = _get_language_config(lang_name)
    
    # Check for universal test file extensions
    ext = os.path.splitext(filepath)[1].lower()
    if ext in UNIVERSAL_TEST_EXT:
        return True
    
    # Check for test directories
    if "/test/" in path_norm or "/tests/" in path_norm or "/spec/" in path_norm:
        return True
    
    # Check for test patterns in filename
    if any(token in base for token in ("test", "spec")):
        return True
    
    # Language-specific heuristics
    if lang_name == "Java" and base.endswith("test.java"):
        return True
    if lang_name == "Python" and (base.startswith("test_") or base.endswith("_test.py")):
        return True
    if lang_name in ["JavaScript", "TypeScript"] and any(base.endswith(suffix) for suffix in ['.test.js', '.test.jsx', '.test.ts', '.test.tsx', '.spec.js', '.spec.jsx', '.spec.ts', '.spec.tsx']):
        return True
    if lang_name == "Go" and base.endswith("_test.go"):
        return True
    
    return False


def print_language_configuration():
    """
    Prints the current language configuration for easy reference.
    """
    print("=" * 80)
    print("LANGUAGE CONFIGURATION")
    print("=" * 80)
    print(f"Target Language: {TARGET_LANGUAGE}")
    print(f"Sheet Name: {SHEET_NAME}")
    print(f"Spreadsheet Key: {SPREADSHEET_KEY}")
    print(f"Output Directory: {get_language_output_dir()}")
    print("-" * 80)
    print(f"Source Extensions: {', '.join(sorted(LANG_CONFIG['source_ext']))}")
    print(f"Dependency Files: {', '.join(sorted(LANG_CONFIG['dependency_files']))}")
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

def get_language_output_dir():
    """
    Returns the language-specific output directory for PR reports.
    Creates the directory if it doesn't exist.
    """
    # Map language names to folder names
    language_folder_map = {
        'Java': 'Java_pr_reports',
        'JavaScript': 'JavaScript_pr_reports', 
        'TypeScript': 'TypeScript_pr_reports',
        'Python': 'Python_pr_reports',
        'Go': 'Go_pr_reports'
    }
    
    # Get the folder name for current language, default to 'Unknown_pr_reports'
    folder_name = language_folder_map.get(TARGET_LANGUAGE, f'{TARGET_LANGUAGE}_pr_reports')
    
    # Create the full path
    output_dir = os.path.join("repo_evaluator", folder_name)
    
    # Create directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    return output_dir

# --- Agent Prompt ---
AGENT_PROMPT = """
You are a senior software engineer evaluating a GitHub issue to determine if it's suitable for a "Good PR".

A "Good PR" is linked to an issue that meets these criteria:
1.  **Clear and Actionable**: It describes a specific, actionable problem or feature, providing enough context for a developer to start working.
2.  **Not a Revert**: The issue must not be a request to simply revert previous changes or roll back to an older version.
3.  **Not a Question or Vague Request**: It must not be a simple user question, a vague request for help, or a request for documentation.
4.  **Single Issue Focus**: The issue should be focused on closing a single, well-defined problem or feature request.
5.  **Primarily in English**: At least 90 percent of the issue content should be written in English.

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

def get_column_indices(header):
    """
    Get column indices from header, case-insensitive.
    If headers are not found, use default values.
    """
    header = [h.lower().strip() for h in header]
    indices = {}
    
    def find_idx(headers_to_check, default_idx):
        for h in headers_to_check:
            try:
                return header.index(h)
            except ValueError:
                continue
        return default_idx

    # Mappings based on the new column order
    indices['user_repo'] = find_idx(['repository'], 0) # Default A
    indices['logical_checks'] = find_idx(['logical checks'], 8) # Default I
    indices['total_prs'] = find_idx(['prs count'], 9) # Default J
    indices['relevant_prs'] = find_idx(['relevant prs count'], 10) # Default K
    indices['agentic_check'] = find_idx(['good prs > 2'], 11) # Default L
    
    return indices

# --- Google Sheets Helper ---
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
        # Create DataFrame with generic column names to avoid parsing issues
        df = pd.DataFrame(data[1:], columns=[f'col_{i}' for i in range(len(header))])
        return df, header
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"❌ Spreadsheet not found. Make sure the key '{spreadsheet_key}' is correct.")
        return None, None
    except Exception as e:
        print(f"❌ Error fetching sheet data: {e}")
        return None, None

def update_sheet_cell(spreadsheet_key, sheet_name, row_index, col_index, value):
    """Updates a single cell in the Google Sheet using a 0-based column index."""
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_JSON_PATH, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)
        sheet.update_cell(row_index, col_index + 1, str(value)) # gspread is 1-based
        print(f"📄 Updated sheet: Row {row_index}, Column {col_index + 1} = {value}")
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
    """Perform language-aware logical checks on PR file list."""
    if not files:
        return None, "No files found in PR."

    lang_cfg = _get_language_config(LANGUAGE)
    allowed_ext = lang_cfg["source_ext"]
    dependency_files = lang_cfg["dependency_files"]

    filenames = [f["filename"] for f in files]

    # ------------------------------------------------------------------
    # 1. Language gate – ensure no files from other *code* languages exist
    # ------------------------------------------------------------------
    disallowed_ext = ALL_SOURCE_EXT - allowed_ext  # dynamic disallowed set

    for fn in filenames:
        ext = os.path.splitext(fn)[1].lower()

        # Skip obvious non-code / text / documentation files
        if ext in NON_CODE_EXT or os.path.basename(fn) in dependency_files:
            continue

        # If file has a code extension but is not part of the target language, fail.
        if ext in disallowed_ext:
            return None, f"Disallowed language file detected: {fn}"

        # Unknown extension that is not explicitly allowed nor in NON_CODE_EXT – assume code and fail.
        if ext not in allowed_ext:
            return None, f"Unknown or binary file type not allowed: {fn}"

    # ------------------------------------------------------------------
    # 2. Split into test / non-test source files for the target language
    # ------------------------------------------------------------------
    test_files = []
    non_test_source_files = []

    for fn in filenames:
        ext = os.path.splitext(fn)[1].lower()
        if ext not in allowed_ext:
            # Non-code or ignored file – skip counts
            continue

        if os.path.basename(fn) in dependency_files:
            continue  # build/dependency file – ignore

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

        if DEBUG_MODE: 
            print(f"\n--- Analyzing PR #{pr_number} ---")
            # Print the full PR data structure in debug mode as requested
            print(f"  - PR Data Dump: {json.dumps(pr, indent=2)}")

        issue_number = extract_issue_number(pr.get('body'))
        if not issue_number:
            if DEBUG_MODE: print(f"  - Skip: No unique issue found.")
            continue
        
        # Get issue details for language filtering
        issue_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
        issue_data = make_github_api_request(issue_url)
        if not issue_data:
            if DEBUG_MODE: print(f"  - Skip: Could not fetch issue #{issue_number}")
            continue
        
        issue_json = issue_data.json()
        
        # Check if the linked item is actually an issue, not a PR
        if issue_json.get('pull_request'):
            if DEBUG_MODE: print(f"  - Skip: Linked item #{issue_number} is a Pull Request, not an Issue.")
            continue
        
        # Language filtering: Issue statement must be in English (90% ASCII)
        issue_body = issue_json.get('body', '')
        if not is_english(issue_body):
            if DEBUG_MODE: print(f"  - Skip: Issue #{issue_number} statement contains too many non-English characters.")
            continue
        
        # Get PR files to analyze code changes in non-test files
        files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
        files = get_pr_files(files_url)
        if not files:
            if DEBUG_MODE: print(f"  - Skip: No files found in PR #{pr_number}")
            continue
        
        # Count additions/deletions only in non-test code files
        lang_cfg = _get_language_config(LANGUAGE)
        allowed_ext = lang_cfg["source_ext"]
        dependency_files = lang_cfg["dependency_files"]
        
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
            
            # Count changes in this non-test code file
            additions = file_info.get('additions', 0)
            deletions = file_info.get('deletions', 0)
            non_test_code_changes += additions + deletions
        
        # Require minimum 20 lines of changes in non-test code files
        if non_test_code_changes < 20:
            if DEBUG_MODE: print(f"  - Skip: PR #{pr_number} has only {non_test_code_changes} lines of changes in non-test code files (minimum 20 required).")
            continue
            
        # Run the original file analysis checks
        status, reason = analyze_pr_files(files)
        if status != "Pass":
            if DEBUG_MODE: print(f"  - Skip: {reason}")
            continue
        
        if DEBUG_MODE: print(f"  - Pass: Meets all logical criteria (non-test code changes: {non_test_code_changes} lines).")
        # Store the issue number with the PR data
        pr_data = pr.copy()
        pr_data['issue_number'] = issue_number
        pr_data['non_test_code_changes'] = non_test_code_changes
        logically_relevant_prs.append(pr_data)

    print(f"✅ Found {len(logically_relevant_prs)} logically relevant PRs out of {len(all_prs)} total PRs checked.")
    return logically_relevant_prs, len(all_prs)

def run_parallel_agentic_checks(prs_to_check, owner, repo):
    """
    Runs agentic checks on multiple PRs in parallel using ThreadPoolExecutor.
    Returns a dictionary of agent decisions for each PR.
    """
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
        # Submit all PRs for processing
        future_to_pr = {executor.submit(process_single_pr, pr): pr for pr in prs_to_check}
        
        # Collect results as they complete
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
    """
    Runs the agentic (LLM) check on a list of logically relevant PRs using parallel processing.
    Stops when the target number of good PRs is found.
    Returns the agent's decision for each PR.
    """
    if not logically_relevant_prs:
        return False, {}

    # Apply threshold to determine how many PRs to process
    total_prs = len(logically_relevant_prs)
    prs_to_process = int(total_prs * PR_PROCESSING_THRESHOLD)
    
    print(f"📊 Processing {prs_to_process}/{total_prs} PRs (threshold: {PR_PROCESSING_THRESHOLD:.1%})")
    
    # Take only the first N PRs based on threshold
    prs_to_check = logically_relevant_prs[:prs_to_process]
    
    good_prs_found = 0
    agent_decisions = {}
    
    if ENABLE_PARALLEL_PROCESSING and len(prs_to_check) > 1:
        print(f"🚀 Using parallel processing with {MAX_WORKERS} workers...")
        agent_decisions = run_parallel_agentic_checks(prs_to_check, owner, repo)
        
        # Count good PRs found
        good_prs_found = sum(1 for decision in agent_decisions.values() 
                           if decision.get('result') == 'Good PR')
        
        # Check if we reached the target
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
    """Writes the list of relevant PRs and their issues to a repo-specific CSV file."""
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
    """
    Runs the agentic PR checker on a single repository.
    This function processes one repo directly without using Google Sheets.
    """
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
    agent_decisions = {}
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

# --- Main Script ---
def main():
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
    
    if DEBUG_MODE:
        print("🕵️ DEBUG MODE ENABLED 🕵️")
        owner, repo = parse_github_url(DEBUG_REPO_URL)
        if owner and repo:
            relevant_prs, total_count = find_logically_relevant_prs(owner, repo)
            print(f"\nTotal PRs: {total_count}, Relevant PRs: {len(relevant_prs)}")
            passed, agent_decisions = run_agentic_check_on_repo(relevant_prs, owner, repo)
            print(f"\nFinal Result for {DEBUG_REPO_URL}: Agentic Check {'Passed' if passed else 'Failed'}")
        return

    print("🚀 Running in Production Mode (using Google Sheets)...")
    sheet_df, header = get_sheet_data(SPREADSHEET_KEY, SHEET_NAME)
    if sheet_df is None: sys.exit(1)
    
    column_indices = get_column_indices(header)
    print(f"Column mapping: {column_indices}")
    
    user_repo_col_idx = column_indices['user_repo']
    logic_col_idx = column_indices['logical_checks']
    agentic_col_idx = column_indices['agentic_check']

    # --- Resume Logic: Find rows that need processing ---
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
                unprocessed_rows.append((index + 2, row)) # Use 1-based index for sheet, +1 for header
    else:
        print("Error: Not enough columns in the sheet to find required columns.")
        return

    print(f"Found {len(unprocessed_rows)} repositories that passed logical checks and need agentic evaluation.")
    
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

        agent_decisions = {}
        if relevant_prs:
            passed, agent_decisions = run_agentic_check_on_repo(relevant_prs, owner, repo)
            write_prs_to_csv(owner, repo, relevant_prs, agent_decisions, get_language_output_dir())
            update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, column_indices['agentic_check'], "Yes" if passed else "No")
        else:
            print("⏭️ Skipping agentic check: No logically relevant PRs found.")
            update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row_index, column_indices['agentic_check'], "No")
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

def parse_command_line_args():
    """
    Parse command line arguments for configuration options.
    """
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
    """
    Update global configuration based on command line arguments.
    """
    global LLM_MODEL, TARGET_GOOD_PRS, ENABLE_PARALLEL_PROCESSING, MAX_WORKERS, PR_PROCESSING_THRESHOLD, DEBUG_MODE, DEBUG_REPO_URL
    
    LLM_MODEL = args.model
    TARGET_GOOD_PRS = args.target_good_prs
    
    if args.no_parallel:
        ENABLE_PARALLEL_PROCESSING = False
    else:
        ENABLE_PARALLEL_PROCESSING = args.parallel
    
    MAX_WORKERS = args.max_workers
    PR_PROCESSING_THRESHOLD = max(0.0, min(1.0, args.threshold))  # Clamp between 0.0 and 1.0
    
    if args.debug:
        DEBUG_MODE = True
        DEBUG_REPO_URL = args.debug_repo

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Analysis interrupted by user.")
        sys.exit(0) 
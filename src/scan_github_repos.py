import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from github import Github, GithubException, RateLimitExceededException
import pandas as pd
from datetime import datetime
import time
import argparse

# --- Configuration ---
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
SHEET_ID = '1XMbstebCi1xFSwJ7cTN-DXv4jFmdH2owWBE3R7YsXK0'
CREDS_FILE = os.path.join(os.path.dirname(__file__), 'creds.json')

# --- Repository Discovery Configuration ---
MIN_STARS = 400  # Minimum stars for repositories
PULL_REPO_COUNT = 10000  # Number of new repos we aim to fetch per run
SKIP_FIRST_RESULTS = 0  # Number of results to skip from the beginning (useful for resuming scans)
CHECK_OTHER_SHEETS = True  # Whether to check other language sheets for repos that should be in target sheet

# Default target language
TARGET_LANGUAGE = "Rust"

# Language to Sheet Name mapping
LANGUAGE_TO_SHEET = {
    "JavaScript": "JS/TS",
    "Java": "Java", 
    "Rust": "Rust",
    "C/C++": "C/C++",
    "Go": "Go"
}

# Language-specific toolchain detection
LANGUAGE_TOOLCHAINS = {
    "Java": {
        "files": ["pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"],
        "description": "Maven or Gradle"
    },
    "JavaScript": {
        "files": ["package.json", "yarn.lock", "pnpm-lock.yaml", "package-lock.json"],
        "description": "npm, yarn, or pnpm"
    },
    "TypeScript": {
        "files": ["package.json", "tsconfig.json", "tsconfig.build.json"],
        "description": "npm with TypeScript"
    },
    "Python": {
        "files": ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "poetry.lock"],
        "description": "pip, poetry, or pipenv"
    },
    "Go": {
        "files": ["go.mod", "go.sum", "Gopkg.toml", "Gopkg.lock"],
        "description": "Go modules or dep"
    },
    "C/C++": {
        "files": ["CMakeLists.txt", "Makefile", "configure", "configure.ac", "autogen.sh", "bootstrap", "build.sh", "setup.py", "package.json", "Cargo.toml", "meson.build", "SConstruct"],
        "description": "CMake, Make, autotools, or other build systems"
    },
    "Rust": {
        "files": ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml"],
        "description": "Cargo"
    }
}


def get_sheet_name_for_language(language):
    """Get the sheet name for a given language."""
    return LANGUAGE_TO_SHEET.get(language, language)

def get_languages_for_sheet(sheet_name):
    """Get the languages that should be scanned for a given sheet name."""
    if sheet_name == "JS/TS":
        return ["JavaScript", "TypeScript"]
    elif sheet_name == "C/C++":
        return ["C/C++"]
    else:
        # For other sheets, return the language that maps to this sheet
        for lang, sheet in LANGUAGE_TO_SHEET.items():
            if sheet == sheet_name:
                return [lang]
    return []

def check_other_language_sheets(gsheet_client, target_language, target_sheet_name):
    """
    Check all language sheets for repositories that have the target language as majority language
    and add them to the target sheet if they don't already exist there.
    """
    if not CHECK_OTHER_SHEETS:
        print("Skipping check of other language sheets (CHECK_OTHER_SHEETS is False)")
        return
    
    print(f"\n=== Checking other language sheets for {target_language} repositories ===")
    
    try:
        # Get existing repos in target sheet
        target_sheet = gsheet_client.open_by_key(SHEET_ID).worksheet(target_sheet_name)
        target_values = target_sheet.get_all_values()
        existing_in_target = {row[0] for row in target_values if len(row) > 0 and row[0].strip()}
        print(f"Found {len(existing_in_target)} existing repositories in target sheet '{target_sheet_name}'")
        
        repos_to_add = []
        
        # Check each language sheet
        for lang, sheet_name in LANGUAGE_TO_SHEET.items():
            if sheet_name == target_sheet_name:
                continue  # Skip the target sheet itself
                
            print(f"\nChecking sheet '{sheet_name}' for {target_language} repositories...")
            
            try:
                sheet = gsheet_client.open_by_key(SHEET_ID).worksheet(sheet_name)
                all_values = sheet.get_all_values()
                
                # Check each row for majority language in column D (index 3)
                for row_idx, row in enumerate(all_values, start=1):
                    if len(row) > 3 and row[3].strip():  # Check if column D has data
                        majority_lang = row[3].strip()
                        repo_name = row[0].strip() if len(row) > 0 and row[0].strip() else ""
                        
                        # Check if this repo has the target language as majority language
                        if majority_lang.lower() == target_language.lower() and repo_name:
                            if repo_name not in existing_in_target and repo_name not in [r[0] for r in repos_to_add]:
                                repo_url = row[2].strip() if len(row) > 2 and row[2].strip() else ""
                                repo_data = [repo_name, '', repo_url]
                                repos_to_add.append(repo_data)
                                print(f"  Found {target_language} repo: {repo_name}")
                
                print(f"  Found {len([r for r in repos_to_add if r[0] in [row[0] for row in all_values if len(row) > 0 and row[0].strip()]])} eligible repositories in '{sheet_name}'")
                
            except gspread.exceptions.WorksheetNotFound:
                print(f"  Warning: Worksheet '{sheet_name}' not found, skipping...")
            except Exception as e:
                print(f"  Error checking sheet '{sheet_name}': {e}")
        
        # Add found repositories to target sheet
        if repos_to_add:
            print(f"\n=== Adding {len(repos_to_add)} repositories from other sheets to '{target_sheet_name}' ===")
            df_to_add = pd.DataFrame(repos_to_add, columns=['USER/REPO', 'Empty', 'URL'])
            update_spreadsheet(gsheet_client, df_to_add, target_sheet_name)
            print(f"Successfully added {len(repos_to_add)} repositories from other language sheets")
        else:
            print(f"\nNo new {target_language} repositories found in other language sheets")
            
    except Exception as e:
        print(f"Error during other language sheets check: {e}")

def authenticate_google_sheets():
    """Authenticates with Google Sheets API using a local credentials file."""
    if not os.path.exists(CREDS_FILE):
        raise FileNotFoundError(f"Credentials file not found at '{CREDS_FILE}'.")
    
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPES)
    client = gspread.authorize(creds)
    return client

def get_github_client():
    """Returns an authenticated GitHub client using environment variable."""
    github_token = os.getenv('GITHUB_TOKEN')
    if not github_token:
        raise ValueError("GITHUB_TOKEN environment variable not set.")
    return Github(github_token)

def has_modern_toolchain(repo, language, cache):
    """
    Checks if a repository contains appropriate build/dependency files for the target language.
    """
    if repo.full_name in cache:
        return cache[repo.full_name]
    
    toolchain_config = LANGUAGE_TOOLCHAINS.get(language)
    if not toolchain_config:
        # If language not configured, accept all repos
        cache[repo.full_name] = True
        return True
    
    try:
        for file in toolchain_config["files"]:
            try:
                repo.get_contents(file)
                cache[repo.full_name] = True
                return True
            except GithubException:
                continue
        cache[repo.full_name] = False
        return False
    except GithubException as e:
        print(f"  [Warning] Could not check toolchain for {repo.full_name}: {e}")
        cache[repo.full_name] = False
        return False

def get_github_language_query(language):
    """
    Converts our language names to GitHub API language queries.
    """
    language_mapping = {
        "Java": "language:java",
        "JavaScript": "language:javascript",
        "TypeScript": "language:typescript",
        "Python": "language:python",
        "Go": "language:go",
        "C/C++": "language:cpp",
        "Rust": "language:rust"
    }
    return language_mapping.get(language, f"language:{language.lower()}")

def get_existing_repositories(gsheet_client, sheet_name):
    """
    Gets a list of all existing repositories from the Google Sheet.
    Returns a set of repository names for efficient duplicate checking.
    """
    try:
        sheet = gsheet_client.open_by_key(SHEET_ID).worksheet(sheet_name)
        print(f"Fetching existing repositories from sheet: '{sheet_name}'")
        
        # Get all values from the sheet
        all_values = sheet.get_all_values()
        
        # Extract repository names from column A (index 0)
        existing_repos = set()
        skipped_rows = 0
        
        for row_idx, row in enumerate(all_values, start=1):
            if len(row) > 0 and row[0].strip():  # Ensure the row has a column A and it's not empty
                repo_name = row[0].strip()
                existing_repos.add(repo_name)
            elif len(row) > 0 and not row[0].strip():
                skipped_rows += 1
            elif len(row) == 0:
                skipped_rows += 1
        
        print(f"Found {len(existing_repos)} existing repositories in sheet")
        if skipped_rows > 0:
            print(f"Skipped {skipped_rows} rows with missing or empty repository names")
        
        return existing_repos, len(all_values)
        
    except gspread.exceptions.WorksheetNotFound:
        print(f"Error: Worksheet '{sheet_name}' not found in spreadsheet '{SHEET_ID}'")
        raise
    except Exception as e:
        print(f"Error fetching existing repositories: {e}")
        raise

def search_github_repos(gh_client, existing_repo_names, max_needed, language, gsheet_client, sheet_name, skip_first=0):
    """
    Fetches repositories using the improved approach from pr_sourcing_linin.py.
    Uses a simple, targeted query approach with toolchain validation.
    Writes repositories to sheet in batches of 100.
    
    Args:
        skip_first: Number of results to skip from the beginning (useful for resuming scans)
    """
    all_new_repos = []
    repo_toolchain_cache = {}
    duplicates_skipped = 0
    toolchain_skipped = 0
    skipped_for_resume = 0
    batch_size = 100  # Write to sheet every 100 repos
    current_batch = []
    
    # Get languages to search for based on sheet name
    languages_to_search = get_languages_for_sheet(sheet_name)
    if not languages_to_search:
        languages_to_search = [language]  # Fallback to original language
    
    print(f"Searching for languages: {languages_to_search}")
    print(f"Target sheet: {sheet_name}")
    print(f"Minimum stars: {MIN_STARS}")
    print(f"Existing repositories to avoid: {len(existing_repo_names)}")
    print(f"Batch size for writing: {batch_size}")
    if skip_first > 0:
        print(f"Skipping first {skip_first} results (resume mode)")
    
    try:
        # Search for each language
        for search_language in languages_to_search:
            if len(all_new_repos) >= max_needed:
                break
                
            print(f"\n=== Searching for {search_language} repositories ===")
            
            # Build the repository query for this language
            language_query = get_github_language_query(search_language)
            repo_query = f"{language_query} stars:>{MIN_STARS} sort:stars-desc"
            
            print(f"GitHub query: {repo_query}")
            print(f"Toolchain requirement: {LANGUAGE_TOOLCHAINS.get(search_language, {}).get('description', 'None')}")
            
            repositories = gh_client.search_repositories(query=repo_query)
            print("Starting repository discovery...")
        
            for repo in repositories:
                # Skip first N results if specified
                if skipped_for_resume < skip_first:
                    print(f"  [Skip Resume] Skipping {repo.full_name} (resume mode: {skipped_for_resume + 1}/{skip_first})")
                    skipped_for_resume += 1
                    continue
                
                if len(all_new_repos) >= max_needed:
                    print(f"\nTarget of {max_needed} repositories reached. Halting search.")
                    break
                
                print(f"\n--- Checking repository: {repo.full_name} (⭐ {repo.stargazers_count}) ---")
                
                # Skip if already in sheet
                if repo.full_name in existing_repo_names:
                    print(f"  [Skip] Repository already exists in sheet.")
                    duplicates_skipped += 1
                    continue
                
                # Skip if already found in this batch
                if repo.full_name in [r[0] for r in all_new_repos]:
                    print(f"  [Skip] Repository already found in this batch.")
                    duplicates_skipped += 1
                    continue
                
                # Check for modern toolchain
                if not has_modern_toolchain(repo, search_language, repo_toolchain_cache):
                    print(f"  [Skip] Repository does not use {LANGUAGE_TOOLCHAINS.get(search_language, {}).get('description', 'required toolchain')}.")
                    toolchain_skipped += 1
                    continue
                
                print(f"  [Pass] Repository is eligible. Adding to list...")
                
                repo_data = [
                    repo.full_name,                        # Column A: USER/REPO
                    '',                                    # Column B: Empty
                    repo.html_url                          # Column C: Full URL
                ]
                
                all_new_repos.append(repo_data)
                current_batch.append(repo_data)
                
                print(f"  [Success] Added {repo.full_name}. Total found: {len(all_new_repos)}/{max_needed}")
                
                # Write batch to sheet when it reaches batch_size
                if len(current_batch) >= batch_size:
                    print(f"\n=== Writing batch of {len(current_batch)} repositories to sheet ===")
                    batch_df = pd.DataFrame(current_batch, columns=['USER/REPO', 'Empty', 'URL'])
                    update_spreadsheet(gsheet_client, batch_df, sheet_name)
                    current_batch = []  # Reset batch
                    print(f"=== Batch written successfully ===")
        
        # Write any remaining repos in the final batch
        if current_batch:
            print(f"\n=== Writing final batch of {len(current_batch)} repositories to sheet ===")
            batch_df = pd.DataFrame(current_batch, columns=['USER/REPO', 'Empty', 'URL'])
            update_spreadsheet(gsheet_client, batch_df, sheet_name)
            print(f"=== Final batch written successfully ===")
        
        # Print summary statistics
        print(f"\n=== Repository Discovery Summary ===")
        print(f"Languages searched: {languages_to_search}")
        print(f"Results skipped for resume: {skipped_for_resume}")
        print(f"New repositories found: {len(all_new_repos)}")
        print(f"Duplicates skipped: {duplicates_skipped}")
        print(f"Toolchain requirement failures: {toolchain_skipped}")
        print(f"Total repositories processed: {len(all_new_repos) + duplicates_skipped + toolchain_skipped}")
            
    except RateLimitExceededException:
        print("Rate limit exceeded during repository search. Please wait and try again.")
        # Write any remaining repos before exiting
        if current_batch:
            print(f"\n=== Writing remaining {len(current_batch)} repositories before exit ===")
            batch_df = pd.DataFrame(current_batch, columns=['USER/REPO', 'Empty', 'URL'])
            update_spreadsheet(gsheet_client, batch_df, sheet_name)
    except Exception as e:
        print(f"An unexpected error occurred during repository search: {e}")
        # Write any remaining repos before exiting
        if current_batch:
            print(f"\n=== Writing remaining {len(current_batch)} repositories before exit ===")
            batch_df = pd.DataFrame(current_batch, columns=['USER/REPO', 'Empty', 'URL'])
            update_spreadsheet(gsheet_client, batch_df, sheet_name)
    
    return pd.DataFrame(all_new_repos, columns=['USER/REPO', 'Empty', 'URL'])

def update_spreadsheet(gsheet_client, df, sheet_name):
    """Updates the Google Sheet with the repository data, avoiding duplicates."""
    if df.empty:
        print("No new repositories to add to spreadsheet.")
        return
        
    try:
        sheet = gsheet_client.open_by_key(SHEET_ID).worksheet(sheet_name)
        print(f"Successfully opened worksheet: '{sheet_name}'")
        
        # Get current sheet data for final duplicate check
        all_values = sheet.get_all_values()
        current_existing_repos = {row[0] for row in all_values if len(row) > 0 and row[0].strip()}

        # Final duplicate check (in case sheet was modified during scanning)
        original_count = len(df)
        df_to_add = df[~df['USER/REPO'].isin(current_existing_repos)]
        new_count = len(df_to_add)
        final_duplicates = original_count - new_count
        
        print(f"Final duplicate check: {original_count} repos found, {new_count} are new, {final_duplicates} duplicates filtered out.")

        if df_to_add.empty:
            print("No new repositories to add after final duplicate check.")
            return
            
        # Convert dataframe to list of lists for gspread
        values_to_append = df_to_add.values.tolist()
        
        # Get the next empty row to append to
        next_row = len(all_values) + 1
        
        # Use update to append data starting at the next empty row
        # Format: 'A{row}:C{row+len-1}' to specify the range
        end_row = next_row + len(values_to_append) - 1
        range_name = f'A{next_row}:C{end_row}'
        sheet.update(values=values_to_append, range_name=range_name)
        print(f"Successfully appended {len(df_to_add)} new rows to the spreadsheet starting at row {next_row}.")

    except gspread.exceptions.WorksheetNotFound:
        print(f"Worksheet with name '{sheet_name}' not found.")
    except Exception as e:
        print(f"An error occurred while updating spreadsheet: {e}")
        raise

def print_configuration():
    """Prints the current configuration for easy reference."""
    sheet_name = get_sheet_name_for_language(TARGET_LANGUAGE)
    print("=" * 80)
    print("REPOSITORY DISCOVERY CONFIGURATION")
    print("=" * 80)
    print(f"Target Language: {TARGET_LANGUAGE}")
    print(f"Sheet Name: {sheet_name}")
    print(f"Minimum Stars: {MIN_STARS}")
    print(f"Target Repository Count: {PULL_REPO_COUNT}")
    print(f"Skip First Results: {SKIP_FIRST_RESULTS}")
    print(f"Check Other Sheets: {CHECK_OTHER_SHEETS}")
    print(f"Sheet ID: {SHEET_ID}")
    print("-" * 80)
    toolchain_desc = LANGUAGE_TOOLCHAINS.get(TARGET_LANGUAGE, {}).get('description', 'None')
    print(f"Toolchain Requirement: {toolchain_desc}")
    print("=" * 80)
    print()

def parse_command_line_args():
    """Parse command line arguments for configuration options."""
    parser = argparse.ArgumentParser(description='GitHub Repository Discovery with skip functionality')
    parser.add_argument('--skip', type=int, default=SKIP_FIRST_RESULTS,
                       help=f'Number of results to skip from the beginning (default: {SKIP_FIRST_RESULTS})')
    parser.add_argument('--count', type=int, default=PULL_REPO_COUNT,
                       help=f'Number of repositories to fetch (default: {PULL_REPO_COUNT})')
    parser.add_argument('--language', type=str, default=TARGET_LANGUAGE,
                       help=f'Target language (default: {TARGET_LANGUAGE})')
    parser.add_argument('--min-stars', type=int, default=MIN_STARS,
                       help=f'Minimum stars required (default: {MIN_STARS})')
    parser.add_argument('--check-other-sheets', action='store_true', default=CHECK_OTHER_SHEETS,
                       help=f'Check other language sheets for repos that should be in target sheet (default: {CHECK_OTHER_SHEETS})')
    parser.add_argument('--no-check-other-sheets', action='store_false', dest='check_other_sheets',
                       help='Disable checking other language sheets')
    
    return parser.parse_args()

def main():
    """Main function to run the script."""
    print("Starting enhanced GitHub repository discovery...")
    
    # Parse command line arguments
    args = parse_command_line_args()
    
    # Update configuration based on command line arguments
    global TARGET_LANGUAGE, PULL_REPO_COUNT, MIN_STARS, SKIP_FIRST_RESULTS, CHECK_OTHER_SHEETS
    TARGET_LANGUAGE = args.language
    PULL_REPO_COUNT = args.count
    MIN_STARS = args.min_stars
    SKIP_FIRST_RESULTS = args.skip
    CHECK_OTHER_SHEETS = args.check_other_sheets
    
    # Get the sheet name for the target language
    sheet_name = get_sheet_name_for_language(TARGET_LANGUAGE)
    
    # Display configuration
    print_configuration()
    
    try:
        gsheet_client = authenticate_google_sheets()
        gh_client = get_github_client()
        
        # First, check other language sheets for repos that should be in target sheet
        check_other_language_sheets(gsheet_client, TARGET_LANGUAGE, sheet_name)
        
        # Get existing repos to check for duplicates
        existing_repos, _ = get_existing_repositories(gsheet_client, sheet_name)
        
        current_repo_count = len(existing_repos)
        print(f"Found {current_repo_count} existing repositories in sheet")

        # Use the full PULL_REPO_COUNT - Google Sheets can handle much more than current data
        max_needed = PULL_REPO_COUNT

        print(f"Will attempt to fetch up to {max_needed} new {TARGET_LANGUAGE} repositories (stars > {MIN_STARS}).")
        if SKIP_FIRST_RESULTS > 0:
            print(f"Will skip the first {SKIP_FIRST_RESULTS} results from GitHub search.")

        repo_df = search_github_repos(gh_client, existing_repos, max_needed, TARGET_LANGUAGE, gsheet_client, sheet_name, SKIP_FIRST_RESULTS)
        
        if repo_df.empty:
            print("No repositories found for the given criteria.")

    except ValueError as e:
        print(f"Configuration error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == '__main__':
    main() 
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from github import Github
import pandas as pd
from datetime import datetime
import time

# --- Constants ---
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
SHEET_ID = '1yRoHc_y5cn_IsvYdRG8bxSPONpuXEDRJ_XCdfxkbmgY'
SHEET_NAME = 'Trainers repositories'
DEFAULT_QUERY = 'sort:updated-desc'  # Base query; star slice will be added dynamically
CREDS_FILE = 'repo_evaluator/creds.json'
PULL_REPO_COUNT = 5000  # Number of new repos we aim to fetch per run
# --- Environment Variables ---
# GITHUB_TOKEN should be set as an environment variable.

def authenticate_google_sheets():
    """Authenticates with Google Sheets API using a local credentials file."""
    if not os.path.exists(CREDS_FILE):
        raise FileNotFoundError(f"Credentials file not found at '{CREDS_FILE}'.")
    
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPES)
    client = gspread.authorize(creds)
    return client

def get_github_client():
    """Returns an authenticated GitHub client."""
    github_token = os.getenv('GITHUB_TOKEN')
    if not github_token:
        raise ValueError("GITHUB_TOKEN environment variable not set.")
    return Github(github_token)

def search_github_repos(gh_client, existing_repo_names, max_needed):
    """Fetches up to `max_needed` repositories with >400 stars not already in the sheet."""
    star_ranges = [
        "50000..100000", "20000..49999", "10000..19999",
        "5000..9999", "2000..4999", "1000..1999", "400..999"
    ]

    all_new_repos = []

    for stars in star_ranges:
        if len(all_new_repos) >= max_needed:
            break

        sliced_query = f"stars:{stars} {DEFAULT_QUERY}"
        print(f"Searching GitHub with query: {sliced_query}")

        try:
            repos = gh_client.search_repositories(sliced_query)

            for repo in repos:
                if repo.full_name in existing_repo_names:
                    continue  # skip duplicates already in sheet

                if repo.full_name in [r[2] for r in all_new_repos]:
                    continue  # skip duplicates within this batch

                all_new_repos.append([
                    datetime.now().strftime('%Y-%m-%d'),  # Column A
                    '',                                    # Column B (empty)
                    repo.full_name,                        # Column C
                    repo.html_url                          # Column D
                ])

                if len(all_new_repos) >= max_needed:
                    break

            print(f"Accumulated {len(all_new_repos)} / {max_needed} repos so far...")

        except Exception as e:
            print(f"Error during search '{sliced_query}': {e}. Retrying after short wait...")
            time.sleep(5)

    return pd.DataFrame(all_new_repos, columns=['Date', 'Empty', 'USER/REPO', 'URL'])

def update_spreadsheet(gsheet_client, df):
    """Updates the Google Sheet with the repository data, avoiding duplicates."""
    try:
        sheet = gsheet_client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        print(f"Successfully opened worksheet: '{SHEET_NAME}'")
        
        # Get all values from the sheet since there are no headers
        all_values = sheet.get_all_values()

        # Get existing USER/REPO from column C (index 2) to avoid duplicates
        existing_repos = set()
        if all_values:
            for row in all_values:
                if len(row) > 2:  # Ensure the row has a column C
                    existing_repos.add(row[2])

        # Filter out repos that are already in the sheet
        original_count = len(df)
        df_to_add = df[~df['USER/REPO'].isin(existing_repos)]
        new_count = len(df_to_add)
        
        print(f"Found {original_count} repos. {new_count} are new.")

        if df_to_add.empty:
            print("No new repositories to add.")
            return
            
        # Determine where to start writing (the row after the last existing row)
        start_row = len(all_values) + 1
        
        # Convert dataframe to list of lists for gspread
        values_to_append = df_to_add.values.tolist()
        
        # Append data
        sheet.update(f'A{start_row}', values_to_append)
        print(f"Successfully appended {len(df_to_add)} new rows to the spreadsheet.")

    except gspread.exceptions.WorksheetNotFound:
        print(f"Worksheet with name '{SHEET_NAME}' not found.")
        # Optionally create it
        # worksheet = gsheet_client.open_by_key(SHEET_ID).add_worksheet(title=SHEET_NAME, rows="100", cols="20")
        # print(f"Created worksheet: '{SHEET_NAME}'")
        # Then you could try to update again.
    except Exception as e:
        print(f"An error occurred: {e}")

def main():
    """Main function to run the script."""
    print(f"Starting GitHub repo scan...")
    try:
        gsheet_client = authenticate_google_sheets()
        gh_client = get_github_client()
        
        # Get existing repos to check for duplicates and count
        sheet = gsheet_client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        all_values = sheet.get_all_values()
        existing_repo_names = {row[2] for row in all_values if len(row) > 2}
        
        current_repo_count = len(all_values)
        total_row_capacity = sheet.row_count
        capacity_left = max(total_row_capacity - current_repo_count, 0)

        print(f"Existing repos/rows: {current_repo_count}. Sheet row capacity: {total_row_capacity}. Empty rows: {capacity_left}.")

        if capacity_left == 0:
            print("No empty rows left in the sheet. Aborting fetch.")
            return

        max_needed = min(PULL_REPO_COUNT, capacity_left)

        print(f"Will attempt to fetch up to {max_needed} new repositories (star > 400).")

        repo_df = search_github_repos(gh_client, existing_repo_names, max_needed)
        
        if not repo_df.empty:
            update_spreadsheet(gsheet_client, repo_df)
        else:
            print("No repositories found for the given query.")

    except ValueError as e:
        print(f"Configuration error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == '__main__':
    main() 
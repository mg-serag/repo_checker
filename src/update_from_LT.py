#!/usr/bin/env python3

import requests
from requests.exceptions import RequestException
from termcolor import colored
import sys
import json
import os
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import time
from datetime import datetime

# --- Script Configuration ---
CREDS_JSON_PATH = os.path.join(os.path.dirname(__file__), 'creds.json')
SCOPE = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
SPREADSHEET_KEY = '1XMbstebCi1xFSwJ7cTN-DXv4jFmdH2owWBE3R7YsXK0'

# --- Labeling Tool Configuration ---
LT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Im1vaGFtYWQuc0B0dXJpbmcuY29tIiwic3ViIjoxMTYsImlhdCI6MTc1MTM1NDgzNiwiZXhwIjoxNzUxOTU5NjM2fQ.ZRwwwAuE8TyZ_NWhEczZoj6j-uujcLzYaHG68VHH7ow"

# --- Sheet Configuration ---
# Configure which sheets to update and their corresponding project IDs
SHEETS_TO_UPDATE = {
    'JS/TS': {
        'project_id': 41,  # JavaScript project ID in labeling tool
        'description': 'JavaScript/TypeScript repositories'
    },
    'Java': {
        'project_id': 42,  # Java project ID in labeling tool
        'description': 'Java repositories'
    }
    # Add more sheets here as needed:
    # 'Python': {
    #     'project_id': 40,
    #     'description': 'Python repositories'
    # },
    # 'Go': {
    #     'project_id': 43,
    #     'description': 'Go repositories'
    # }
}

# --- Column Configuration ---
# Define expected column headers and their default indices (0-based)
COLUMN_CONFIG = {
    'user_repo': {
        'headers': ['repository'],
        'default_index': 0,  # Column A
        'description': 'Repository name in USER/REPO format'
    },
    'repo_url': {
        'headers': ['actual repository link'],
        'default_index': 2,  # Column C
        'description': 'Full GitHub repository URL'
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

# --- Labeling Tool API Functions ---

def fetch_all_batches_from_lt(project_id):
    """
    Fetches all batch data from the labeling tool API for a specific project.
    Returns a dictionary mapping USER__REPO to batch data.
    """
    base_url = f"https://eval.turing.com/api/batches?sort%5B0%5D=createdAt%2CDESC&join%5B0%5D=batchStats&join%5B1%5D=importAttempts&filter%5B0%5D=projectId%7C%7C%24eq%7C%7C{project_id}"
    headers = {"Authorization": f"Bearer {LT_TOKEN}"}
    all_batches = []
    page = 1
    limit = 100

    print(f"\n[Labeling Tool] Fetching all batch data for project ID: {project_id}...")

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

def update_sheet_from_LT(json_path, spreadsheet_key, scope, sheet_name, column_indices, project_id):
    """
    Updates the sheet with data from the labeling tool for all repositories.
    Updates columns O (Added), P (Tasks Count in LT), Q (Improper in LT), R (Batch link), and S (Addition Date).
    """
    print(f"\n=== Starting Labeling Tool Data Update for {sheet_name} (Project ID: {project_id}) ===")
    
    # Fetch all batch data from labeling tool
    batch_data = fetch_all_batches_from_lt(project_id)
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
                        # Rule 1: "Yes" row found -> Refresh counts and ensure batch link exists
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
                            gspread.Cell(sheet_row, tasks_count_col_idx_1, total_tasks),
                            gspread.Cell(sheet_row, improper_col_idx_1, improper_tasks),
                            gspread.Cell(sheet_row, batch_link_col_idx_1, batch_link),
                            gspread.Cell(sheet_row, addition_date_col_idx_1, addition_date),
                        ])
                        refreshed_count += 1
                        print(f"  Refreshed counts and ensured batch link for existing repo in row {sheet_row}: {user_repo}")
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
                    # Mark as "No" and clear fields
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
                print(colored(f"\nSuccessfully updated {sheet_name}: " + " and ".join(log_parts) + ".", "green"))
            else:
                print(colored(f"\nNo updatable repositories found in {sheet_name} matching the criteria in the labeling tool.", "yellow"))
        else:
            print(colored(f"No updates were made to {sheet_name}.", "yellow"))
            
    except Exception as e:
        print(colored(f"Error updating sheet {sheet_name} with labeling tool data: {e}", "red"))
        import traceback
        print(colored(f"Full traceback: {traceback.format_exc()}", "red"))

def print_configuration():
    """
    Prints the current configuration for easy reference.
    """
    print("=" * 80)
    print("UPDATE FROM LABELING TOOL CONFIGURATION")
    print("=" * 80)
    print(f"Spreadsheet Key: {SPREADSHEET_KEY}")
    print(f"Sheets to Update: {len(SHEETS_TO_UPDATE)}")
    print("-" * 80)
    
    for sheet_name, config in SHEETS_TO_UPDATE.items():
        print(f"Sheet: {sheet_name}")
        print(f"  Project ID: {config['project_id']}")
        print(f"  Description: {config['description']}")
        print()
    
    print("Columns to Update:")
    print("  O - Added (Yes/No)")
    print("  P - Tasks Count in LT")
    print("  Q - Improper in LT")
    print("  R - Batch Link")
    print("  S - Addition Date")
    print("=" * 80)
    print()

def main():
    """
    Main script to update specified sheets with labeling tool data.
    """
    print("--- Starting Labeling Tool Data Update ---")
    
    # Display configuration
    print_configuration()
    
    # Process each configured sheet
    for sheet_name, config in SHEETS_TO_UPDATE.items():
        print(f"\n{'='*60}")
        print(f"Processing Sheet: {sheet_name}")
        print(f"{'='*60}")
        
        try:
            # Fetch sheet data to get headers
            print(f"Fetching data from sheet: {sheet_name}")
            sheet_df, header = fetch_sheet_data(
                CREDS_JSON_PATH,
                SPREADSHEET_KEY,
                SCOPE,
                sheet_name=sheet_name
            )
            
            if sheet_df.empty:
                print(colored(f"Sheet {sheet_name} is empty or has no data.", "yellow"))
                continue
            
            print(f"Found {len(sheet_df)} rows in {sheet_name}")
            
            # Get column indices from header
            column_indices = get_column_indices(header)
            
            # Update the sheet with labeling tool data
            update_sheet_from_LT(
                CREDS_JSON_PATH,
                SPREADSHEET_KEY,
                SCOPE,
                sheet_name,
                column_indices,
                config['project_id']
            )
            
        except gspread.exceptions.SpreadsheetNotFound:
            print(colored(f"Error: Spreadsheet not found. Make sure the key '{SPREADSHEET_KEY}' is correct and you have shared the sheet with the service account email.", "red"))
            continue
        except gspread.exceptions.WorksheetNotFound:
            print(colored(f"Error: Worksheet '{sheet_name}' not found in the spreadsheet.", "red"))
            continue
        except Exception as e:
            print(colored(f"Error processing sheet {sheet_name}: {e}", "red"))
            continue
    
    print("\n--- Labeling Tool Data Update Complete ---")

if __name__ == "__main__":
    main() 
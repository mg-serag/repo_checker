#!/usr/bin/env python3
"""
Centralized Sheet Utilities

This module provides centralized management for all Google Sheets operations,
including column mapping, data fetching, and updating across all scripts.
"""

import os
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from typing import Dict, List, Tuple, Optional, Any
from termcolor import colored

# --- Configuration ---
CREDS_JSON_PATH = os.path.join(os.path.dirname(__file__), 'creds.json')
SCOPE = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

# --- Column Configuration ---
# Updated column mapping as requested
COLUMN_CONFIG = {
    'repository': {
        'headers': ['repository'],
        'default_index': 0,  # Column A
        'description': 'Repository name in USER/REPO format'
    },
    'repo_url': {
        'headers': ['actual repository link'],
        'default_index': 1,  # Column B
        'description': 'Full GitHub repository URL'
    },
    'majority_language': {
        'headers': ['majority language'],
        'default_index': 2,  # Column C
        'description': 'Primary programming language'
    },
    'percentage': {
        'headers': ['%'],
        'default_index': 3,  # Column D
        'description': 'Percentage of majority language'
    },
    'stars': {
        'headers': ['stars'],
        'default_index': 4,  # Column E
        'description': 'GitHub star count'
    },
    'loc': {
        'headers': ['loc'],
        'default_index': 5,  # Column F
        'description': 'Lines of code count'
    },
    'logical_checks': {
        'headers': ['logical checks'],
        'default_index': 6,  # Column G
        'description': 'Result of logical evaluation checks'
    },
    'prs_count': {
        'headers': ['prs count'],
        'default_index': 7,  # Column H
        'description': 'Total PRs count'
    },
    'relevant_prs_count': {
        'headers': ['relevant prs count'],
        'default_index': 8,  # Column I
        'description': 'Relevant PRs count'
    },
    'good_prs_gt_2': {
        'headers': ['good prs > 2'],
        'default_index': 9,  # Column J
        'description': 'Good PRs > 2 count'
    },
    'added': {
        'headers': ['added'],
        'default_index': 10,  # Column K
        'description': 'Whether repo was added to final list'
    },
    'tasks_count_lt': {
        'headers': ['tasks count in lt'],
        'default_index': 11,  # Column L
        'description': 'Total tasks count in labeling tool'
    },
    'improper_lt': {
        'headers': ['improper in lt'],
        'default_index': 12,  # Column M
        'description': 'Count of improper tasks in labeling tool'
    },
    'completed_lt': {
        'headers': ['completed in lt'],
        'default_index': 13,  # Column N
        'description': 'Count of completed tasks in labeling tool'
    },
    'unclaimed_lt': {
        'headers': ['unclaimed in lt'],
        'default_index': 14,  # Column O
        'description': 'Count of unclaimed tasks in labeling tool'
    },
    'batch_link': {
        'headers': ['batch link'],
        'default_index': 15,  # Column P
        'description': 'Link to the batch in labeling tool'
    },
    'addition_date': {
        'headers': ['addition date'],
        'default_index': 16,  # Column Q
        'description': 'Date when the repository was added to labeling tool'
    }
}

# --- Google Sheets Client Management ---

# Build a global credentials object lazily so we don't recreate it for every
# Sheets call.
_GCRED = None

def _get_gspread_client(json_path: str = None, scopes: List[str] = None) -> gspread.Client:
    """Return a cached gspread client authorised with the service account."""
    global _GCRED
    if _GCRED is None:
        json_path = json_path or CREDS_JSON_PATH
        scopes = scopes or SCOPE
        _GCRED = Credentials.from_service_account_file(json_path, scopes=scopes)
    return gspread.Client(auth=_GCRED)

def get_spreadsheet_key() -> str:
    """Get the spreadsheet key from config_utils."""
    from config_utils import get_spreadsheet_key as get_key
    return get_key()

def get_google_sheet(client: gspread.Client = None, spreadsheet_key: str = None) -> gspread.Spreadsheet:
    """Get the Google Sheet object."""
    if client is None:
        client = _get_gspread_client()
    if spreadsheet_key is None:
        spreadsheet_key = get_spreadsheet_key()
    return client.open_by_key(spreadsheet_key)

# --- Column Index Management ---

def get_column_indices(header: List[str]) -> Dict[str, int]:
    """
    Get column indices from header using the COLUMN_CONFIG.
    Shows which columns were found by header name vs. using defaults.
    
    Args:
        header: List of header strings from the sheet
        
    Returns:
        Dictionary mapping column keys to their indices
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

def get_column_letter(index: int) -> str:
    """Convert column index to Excel column letter."""
    if index < 26:
        return chr(65 + index)
    else:
        return f"Column {index + 1}"

# --- Data Fetching ---

def fetch_sheet_data(sheet_name: str = None, client: gspread.Client = None, 
                    spreadsheet_key: str = None) -> Tuple[pd.DataFrame, List[str]]:
    """
    Fetches data and header from a Google Sheet.
    
    Args:
        sheet_name: Name of the sheet to fetch (None for first sheet)
        client: gspread client (None to create new)
        spreadsheet_key: Spreadsheet key (None to get from config)
        
    Returns:
        Tuple of (DataFrame, header_list)
    """
    if client is None:
        client = _get_gspread_client()
    if spreadsheet_key is None:
        spreadsheet_key = get_spreadsheet_key()
    
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

def get_existing_repositories(sheet_name: str, client: gspread.Client = None, 
                            spreadsheet_key: str = None) -> Tuple[set, int]:
    """
    Gets a list of all existing repositories from the Google Sheet.
    Also checks the Scrap sheet to avoid duplicates there.
    
    Args:
        sheet_name: Name of the sheet to check
        client: gspread client (None to create new)
        spreadsheet_key: Spreadsheet key (None to get from config)
        
    Returns:
        Tuple of (set of repository names, total rows count)
    """
    if client is None:
        client = _get_gspread_client()
    if spreadsheet_key is None:
        spreadsheet_key = get_spreadsheet_key()
    
    try:
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)
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
        
        # Also check the Scrap sheet for duplicates
        try:
            scrap_sheet = client.open_by_key(spreadsheet_key).worksheet("Scrap")
            scrap_values = scrap_sheet.get_all_values()
            scrap_repos = {row[0].strip() for row in scrap_values if len(row) > 0 and row[0].strip()}
            existing_repos.update(scrap_repos)
            print(f"Found {len(scrap_repos)} additional repositories in Scrap sheet")
        except gspread.exceptions.WorksheetNotFound:
            print("Scrap sheet not found, skipping Scrap sheet duplicate check")
        except Exception as e:
            print(f"Error checking Scrap sheet: {e}")
        
        return existing_repos, len(all_values)
        
    except gspread.exceptions.WorksheetNotFound:
        print(f"Error: Worksheet '{sheet_name}' not found in spreadsheet '{spreadsheet_key}'")
        raise
    except Exception as e:
        print(f"Error fetching existing repositories: {e}")
        raise

# --- Data Updating ---

def update_sheet_cells(sheet_name: str, cell_updates: List[gspread.Cell], 
                      client: gspread.Client = None, spreadsheet_key: str = None) -> bool:
    """
    Update multiple cells in a sheet.
    
    Args:
        sheet_name: Name of the sheet to update
        cell_updates: List of gspread.Cell objects to update
        client: gspread client (None to create new)
        spreadsheet_key: Spreadsheet key (None to get from config)
        
    Returns:
        True if successful, False otherwise
    """
    if not cell_updates:
        return True
        
    try:
        if client is None:
            client = _get_gspread_client()
        if spreadsheet_key is None:
            spreadsheet_key = get_spreadsheet_key()
        
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)
        sheet.update_cells(cell_updates, value_input_option='USER_ENTERED')
        return True
        
    except Exception as e:
        print(colored(f"Error updating sheet {sheet_name}: {e}", "red"))
        return False

def update_sheet_row(sheet_name: str, row_index: int, column_indices: Dict[str, int], 
                    data: Dict[str, Any], client: gspread.Client = None, 
                    spreadsheet_key: str = None) -> bool:
    """
    Update a single row in a sheet with data.
    
    Args:
        sheet_name: Name of the sheet to update
        row_index: Row index (1-based)
        column_indices: Column index mapping
        data: Dictionary of column_key -> value to update
        client: gspread client (None to create new)
        spreadsheet_key: Spreadsheet key (None to get from config)
        
    Returns:
        True if successful, False otherwise
    """
    cell_updates = []
    
    for column_key, value in data.items():
        if column_key in column_indices:
            col_index = column_indices[column_key] + 1  # Convert to 1-based
            cell_updates.append(gspread.Cell(row_index, col_index, value))
    
    return update_sheet_cells(sheet_name, cell_updates, client, spreadsheet_key)

def append_sheet_rows(sheet_name: str, rows_data: List[List], 
                     client: gspread.Client = None, spreadsheet_key: str = None) -> bool:
    """
    Append rows to a sheet.
    
    Args:
        sheet_name: Name of the sheet to update
        rows_data: List of row data (list of lists)
        client: gspread client (None to create new)
        spreadsheet_key: Spreadsheet key (None to get from config)
        
    Returns:
        True if successful, False otherwise
    """
    if not rows_data:
        return True
        
    try:
        if client is None:
            client = _get_gspread_client()
        if spreadsheet_key is None:
            spreadsheet_key = get_spreadsheet_key()
        
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)
        
        # Get current data to find next empty row
        all_values = sheet.get_all_values()
        next_row = len(all_values) + 1
        
        # Append the data
        end_row = next_row + len(rows_data) - 1
        range_name = f'A{next_row}:{get_column_letter(len(rows_data[0])-1)}{end_row}'
        sheet.update(values=rows_data, range_name=range_name)
        
        return True
        
    except Exception as e:
        print(colored(f"Error appending rows to sheet {sheet_name}: {e}", "red"))
        return False

# --- Utility Functions ---

def print_column_configuration():
    """Prints the current column configuration for easy reference."""
    print("=" * 80)
    print("SHEET COLUMN CONFIGURATION")
    print("=" * 80)
    print(f"{'Column Key':<20} {'Excel':<8} {'Expected Headers':<25} {'Description'}")
    print("-" * 80)
    
    for column_key, config in COLUMN_CONFIG.items():
        excel_col = get_column_letter(config['default_index'])
        headers_str = ", ".join(config['headers'])
        if len(headers_str) > 24:
            headers_str = headers_str[:21] + "..."
        print(f"{column_key:<20} {excel_col:<8} {headers_str:<25} {config['description']}")
    
    print("=" * 80)
    print()

def safe_gspread_call(func, *args, **kwargs):
    """Wrapper to safely call gspread operations with basic retry on 429 quota errors."""
    MAX_RETRIES = 5
    RATE_LIMIT_SLEEP_SEC = 60
    
    for attempt in range(MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "429" in str(e) or "Quota exceeded" in str(e):
                print(f"Quota exceeded. Waiting {RATE_LIMIT_SLEEP_SEC} seconds before retrying (attempt {attempt + 1}/{MAX_RETRIES}) ...")
                import time
                time.sleep(RATE_LIMIT_SLEEP_SEC)
                continue
            raise
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries for gspread call {func.__name__}") 
#!/usr/bin/env python3

import requests
from termcolor import colored
import os
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import time
from requests.exceptions import ConnectionError

# --- Script Configuration ---
from config_utils import get_spreadsheet_key
SPREADSHEET_KEY = get_spreadsheet_key()

# --- Labeling Tool Configuration ---
from config_utils import get_lt_token
LT_TOKEN = get_lt_token()

# --- Sheet Configuration ---
# Import centralized configuration functions
from config_utils import (
    get_all_language_configs
)

# Import centralized sheet utilities
from sheet_utils import (
    get_column_indices, fetch_sheet_data, update_sheet_cells,
    _get_gspread_client, get_spreadsheet_key, print_column_configuration
)

def get_sheets_to_update():
    """
    Dynamically generate sheets to update configuration from language_configs.json
    
    Returns:
        Dictionary mapping sheet names to their configuration
    """
    try:
        all_languages = get_all_language_configs()
        sheets_config = {}
        
        for lang_name, lang_config in all_languages.items():
            sheet_name = lang_config.get('sheet_name', '')
            if sheet_name and sheet_name not in sheets_config:
                # Get project ID from top level
                project_id = lang_config.get('project_id')
                if project_id:
                    sheets_config[sheet_name] = {
                        'project_id': project_id,
                        'description': f'{lang_name} repositories'
                    }
                    # Log Python specifically to verify it's included
                    if lang_name == 'Python':
                        print(f"[Config] Python loaded: Sheet='{sheet_name}', Project ID={project_id}")
        
        return sheets_config
    except (FileNotFoundError, KeyError) as e:
        print(f"Warning: Could not load language configs, using fallback: {e}")
        # Fallback configuration
        return {
            'Python': {
                'project_id': 40,
                'description': 'Python repositories'
            },
            'JS/TS': {
                'project_id': 41,
                'description': 'JavaScript/TypeScript repositories'
            },
            'Java': {
                'project_id': 42,
                'description': 'Java repositories'
            },
            'Go': {
                'project_id': 43,
                'description': 'Go repositories'
            },
            'C/C++': {
                'project_id': 44,
                'description': 'C/C++ repositories'
            },
            'Ruby': {
                'project_id': 45,
                'description': 'Ruby repositories'
            },
            'Rust': {
                'project_id': 46,
                'description': 'Rust repositories'
            },
            'C#': {
                'project_id': 47,
                'description': 'C# repositories'
            }
        }

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

def find_repository_batches(repo_key, batch_data):
    """
    Find all batches for a repository including parts (USER__REPO, USER__REPO_part_002, etc.)
    
    Args:
        repo_key: Base repository key in USER__REPO format
        batch_data: Dictionary of all batch data
        
    Returns:
        List of batch objects that match the repository
    """
    matching_batches = []
    
    for batch_name, batch in batch_data.items():
        if batch is None:
            continue
            
        # Check for exact match or part match
        if batch_name == repo_key or batch_name.startswith(f"{repo_key}_part_"):
            matching_batches.append(batch)
    
    return matching_batches

def aggregate_batch_data(batches):
    """
    Aggregate data from multiple repository batches.
    
    Args:
        batches: List of batch objects to aggregate
        
    Returns:
        Dictionary with aggregated data or None if no valid batches
    """
    if not batches:
        return None
    
    # Use the first batch as the base (usually the main batch without _part_)
    main_batch = batches[0]
    
    # Find the main batch (without _part_ suffix) if it exists
    for batch in batches:
        batch_name = batch.get("name", "")
        if batch_name and "_part_" not in batch_name:
            main_batch = batch
            break
    
    # Initialize aggregated values
    total_conversations = 0
    total_improper = 0
    total_completed = 0
    total_unclaimed = 0
    earliest_date = None
    batch_links = []
    batch_names = []
    
    for batch in batches:
        if batch is None:
            continue
            
        batch_name = batch.get("name", "")
        batch_id = batch.get("id")
        
        # Aggregate conversation counts
        conversations = batch.get("countOfConversations", 0) or 0
        total_conversations += conversations
        
        # Aggregate improper counts
        batch_stats = batch.get("batchStats", {}) or {}
        improper = batch_stats.get("improper", 0) if batch_stats else 0
        total_improper += improper
        
        # Aggregate completed and unclaimed (pending) counts from batch stats
        completed_count = batch_stats.get("completed", 0) if batch_stats else 0
        unclaimed_count = batch_stats.get("pending", 0) if batch_stats else 0
        total_completed += completed_count
        total_unclaimed += unclaimed_count
        
        # Log task status counts for debugging
        if completed_count > 0 or unclaimed_count > 0:
            print(f"    Batch {batch_name}: {completed_count} completed, {unclaimed_count} unclaimed tasks")
        
        # Track earliest creation date
        created_at = batch.get("createdAt")
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                if earliest_date is None or dt < earliest_date:
                    earliest_date = dt
            except (ValueError, AttributeError):
                pass
        
        # Collect batch information for linking
        if batch_id:
            batch_links.append(f"https://eval.turing.com/batches/{batch_id}/view")
            batch_names.append(batch_name)
    
    # Create aggregated result
    result = {
        "id": main_batch.get("id"),  # Use main batch ID for primary link
        "name": main_batch.get("name"),
        "countOfConversations": total_conversations,
        "batchStats": {"improper": total_improper},
        "createdAt": main_batch.get("createdAt"),  # Use main batch creation date
        "aggregated_stats": {
            "total_batches": len(batches),
            "batch_names": batch_names,
            "batch_links": batch_links,
            "earliest_date": earliest_date.isoformat() if earliest_date else None,
            "total_conversations": total_conversations,
            "total_improper": total_improper,
            "total_completed": total_completed,
            "total_unclaimed": total_unclaimed
        }
    }
    
    return result

def update_sheet_from_LT(sheet_name, column_indices, project_id):
    """
    Updates the sheet with data from the labeling tool for all repositories.
    Now handles multiple batch parts and aggregates data from all parts.
    Updates columns K (Added), L (Tasks Count in LT), M (Improper in LT), 
    N (Completed in LT), O (Unclaimed in LT), P (Batch link), and Q (Addition Date).
    """
    print(f"\n=== Starting Labeling Tool Data Update for {sheet_name} (Project ID: {project_id}) ===")
    
    # Fetch all batch data from labeling tool
    batch_data = fetch_all_batches_from_lt(project_id)
    if not batch_data:
        print(colored("No batch data found in labeling tool. Skipping update.", "yellow"))
        return
    
    try:
        # Fetch current sheet data using centralized utilities
        sheet_df, header = fetch_sheet_data(sheet_name)
        
        if sheet_df.empty:
            print(colored("Sheet is empty or has no data rows.", "yellow"))
            return
        
        data_rows = sheet_df.values.tolist()
        
        # Get column indices for the new columns
        user_repo_col_idx = column_indices['repository']
        added_col_0_idx = column_indices['added']
        
        added_col_idx_1 = column_indices['added'] + 1
        tasks_count_col_idx_1 = column_indices['tasks_count_lt'] + 1
        improper_col_idx_1 = column_indices['improper_lt'] + 1
        completed_col_idx_1 = column_indices['completed_lt'] + 1
        unclaimed_col_idx_1 = column_indices['unclaimed_lt'] + 1
        batch_link_col_idx_1 = column_indices['batch_link'] + 1
        addition_date_col_idx_1 = column_indices['addition_date'] + 1
        
        # Check if we have enough columns in the data
        max_col_needed = max(user_repo_col_idx, column_indices['added'], 
                           column_indices['tasks_count_lt'], column_indices['improper_lt'],
                           column_indices['completed_lt'], column_indices['unclaimed_lt'],
                           column_indices['batch_link'], column_indices['addition_date'])
        
        if max_col_needed >= len(data_rows[0]) if data_rows else 0:
            print(colored(f"Warning: Sheet may not have enough columns. Need at least {max_col_needed + 1} columns.", "yellow"))
        
        print(f"Updating columns: K (Added), L (Tasks Count), M (Improper), N (Completed), O (Unclaimed), P (Batch Link), Q (Addition Date)")
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
            aggregated_repo_data = None

            # Try to find all batches for this repository (including parts)
            if user_repo and '/' in user_repo:
                lt_key = user_repo.replace('/', '__')
                
                # Find all batches for this repository
                matching_batches = find_repository_batches(lt_key, batch_data)
                
                if matching_batches:
                    # Aggregate data from all matching batches
                    aggregated_repo_data = aggregate_batch_data(matching_batches)
                    
                    # Log the aggregation details
                    if len(matching_batches) > 1:
                        batch_names = [b.get("name", "Unknown") for b in matching_batches]
                        print(f"  Found {len(matching_batches)} batches for {user_repo}: {', '.join(batch_names)}")

            # Apply rules based on "Added" column status
            if current_added_status == 'yes':
                if aggregated_repo_data:
                    try:
                        # Rule 1: "Yes" row found -> Refresh counts and ensure batch link exists
                        batch_id = aggregated_repo_data.get("id")
                        aggregated_stats = aggregated_repo_data.get("aggregated_stats", {})
                        total_tasks = aggregated_stats.get("total_conversations", 0)
                        improper_tasks = aggregated_stats.get("total_improper", 0)
                        completed_tasks = aggregated_stats.get("total_completed", 0)
                        unclaimed_tasks = aggregated_stats.get("total_unclaimed", 0)
                        
                        # Create batch link - use main batch or show summary if multiple
                        if batch_id:
                            batch_link = f"https://eval.turing.com/batches/{batch_id}/view"
                            if aggregated_stats.get("total_batches", 1) > 1:
                                batch_link += f" ({aggregated_stats['total_batches']} parts)"
                        else:
                            batch_link = ""
                        
                        # Parse addition date from earliest date or main batch
                        addition_date = ""
                        earliest_date_str = aggregated_stats.get("earliest_date")
                        if earliest_date_str:
                            try:
                                dt = datetime.fromisoformat(earliest_date_str)
                                addition_date = dt.strftime('%Y-%m-%d')
                            except (ValueError, AttributeError) as e:
                                print(f"  Warning: Could not parse earliest date for {user_repo}: {earliest_date_str} - {e}")
                        
                        cell_updates.extend([
                            gspread.Cell(sheet_row, tasks_count_col_idx_1, total_tasks),
                            gspread.Cell(sheet_row, improper_col_idx_1, improper_tasks),
                            gspread.Cell(sheet_row, completed_col_idx_1, completed_tasks),
                            gspread.Cell(sheet_row, unclaimed_col_idx_1, unclaimed_tasks),
                            gspread.Cell(sheet_row, batch_link_col_idx_1, batch_link),
                            gspread.Cell(sheet_row, addition_date_col_idx_1, addition_date),
                        ])
                        refreshed_count += 1
                        
                        if aggregated_stats.get("total_batches", 1) > 1:
                            print(f"  Refreshed aggregated data for {user_repo} in row {sheet_row}: {total_tasks} tasks from {aggregated_stats['total_batches']} batches")
                        else:
                            print(f"  Refreshed data for {user_repo} in row {sheet_row}: {total_tasks} tasks")
                        
                        # Log task status breakdown
                        if completed_tasks > 0 or unclaimed_tasks > 0:
                            print(f"    Task breakdown: {completed_tasks} completed, {unclaimed_tasks} unclaimed, {improper_tasks} improper")
                    except Exception as e:
                        print(f"  Error processing existing repo {user_repo} in row {sheet_row}: {e}")
                # else: Do nothing, as requested for "Yes" rows not found in LT
            
            else:  # Rule 2: "No" or empty "Added" column -> Perform full update
                if aggregated_repo_data:
                    try:
                        # Full update for newly found repo
                        batch_id = aggregated_repo_data.get("id")
                        aggregated_stats = aggregated_repo_data.get("aggregated_stats", {})
                        total_tasks = aggregated_stats.get("total_conversations", 0)
                        improper_tasks = aggregated_stats.get("total_improper", 0)
                        completed_tasks = aggregated_stats.get("total_completed", 0)
                        unclaimed_tasks = aggregated_stats.get("total_unclaimed", 0)
                        
                        # Create batch link - use main batch or show summary if multiple
                        if batch_id:
                            batch_link = f"https://eval.turing.com/batches/{batch_id}/view"
                            if aggregated_stats.get("total_batches", 1) > 1:
                                batch_link += f" ({aggregated_stats['total_batches']} parts)"
                        else:
                            batch_link = ""
                        
                        # Parse addition date from earliest date or main batch
                        addition_date = ""
                        earliest_date_str = aggregated_stats.get("earliest_date")
                        if earliest_date_str:
                            try:
                                dt = datetime.fromisoformat(earliest_date_str)
                                addition_date = dt.strftime('%Y-%m-%d')
                            except (ValueError, AttributeError) as e:
                                print(f"  Warning: Could not parse earliest date for {user_repo}: {earliest_date_str} - {e}")
                        
                        cell_updates.extend([
                            gspread.Cell(sheet_row, added_col_idx_1, "Yes"),
                            gspread.Cell(sheet_row, tasks_count_col_idx_1, total_tasks),
                            gspread.Cell(sheet_row, improper_col_idx_1, improper_tasks),
                            gspread.Cell(sheet_row, completed_col_idx_1, completed_tasks),
                            gspread.Cell(sheet_row, unclaimed_col_idx_1, unclaimed_tasks),
                            gspread.Cell(sheet_row, batch_link_col_idx_1, batch_link),
                            gspread.Cell(sheet_row, addition_date_col_idx_1, addition_date)
                        ])
                        updated_count += 1
                        
                        if aggregated_stats.get("total_batches", 1) > 1:
                            print(f"  Updated row {sheet_row}: Found {user_repo} with {total_tasks} tasks from {aggregated_stats['total_batches']} batches in LT.")
                        else:
                            print(f"  Updated row {sheet_row}: Found {user_repo} with {total_tasks} tasks in LT.")
                    except Exception as e:
                        print(f"  Error processing new repo {user_repo} in row {sheet_row}: {e}")
                else:
                    # Mark as "No" and clear fields
                    cell_updates.extend([
                        gspread.Cell(sheet_row, added_col_idx_1, "No"),
                        gspread.Cell(sheet_row, tasks_count_col_idx_1, ""),
                        gspread.Cell(sheet_row, improper_col_idx_1, ""),
                        gspread.Cell(sheet_row, completed_col_idx_1, ""),
                        gspread.Cell(sheet_row, unclaimed_col_idx_1, ""),
                        gspread.Cell(sheet_row, batch_link_col_idx_1, ""),
                        gspread.Cell(sheet_row, addition_date_col_idx_1, "")
                    ])
        
        # Batch update all cells for efficiency using centralized utilities
        if cell_updates:
            success = update_sheet_cells(sheet_name, cell_updates)
            if success:
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
                print(colored(f"Failed to update {sheet_name}.", "red"))
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
    sheets_to_update = get_sheets_to_update()
    
    print("=" * 80)
    print("UPDATE FROM LABELING TOOL CONFIGURATION")
    print("=" * 80)
    print(f"Spreadsheet Key: {get_spreadsheet_key()}")
    print(f"Sheets to Update: {len(sheets_to_update)}")
    print("-" * 80)
    
    for sheet_name, config in sheets_to_update.items():
        print(f"Sheet: {sheet_name}")
        print(f"  Project ID: {config['project_id']}")
        print(f"  Description: {config['description']}")
        print()
    
    print("Columns to Update:")
    print("  K - Added (Yes/No)")
    print("  L - Tasks Count in LT")
    print("  M - Improper in LT")
    print("  N - Completed in LT")
    print("  O - Unclaimed in LT")
    print("  P - Batch Link")
    print("  Q - Addition Date")
    print("=" * 80)
    print()

def main():
    """
    Main script to update specified sheets with labeling tool data.
    """
    print("--- Starting Labeling Tool Data Update ---")
    
    # Display configuration
    print_configuration()
    
    # Get dynamic sheets configuration
    sheets_to_update = get_sheets_to_update()
    
    # Process each configured sheet
    for sheet_name, config in sheets_to_update.items():
        print(f"\n{'='*60}")
        print(f"Processing Sheet: {sheet_name}")
        print(f"{'='*60}")
        
        retries = 3
        delay = 5  # seconds

        for attempt in range(retries):
            try:
                # Fetch sheet data to get headers using centralized utilities
                print(f"Fetching data from sheet: {sheet_name}")
                sheet_df, header = fetch_sheet_data(sheet_name)
                
                if sheet_df.empty:
                    print(colored(f"Sheet {sheet_name} is empty or has no data.", "yellow"))
                    break
                
                print(f"Found {len(sheet_df)} rows in {sheet_name}")
                
                # Get column indices from header using centralized utilities
                column_indices = get_column_indices(header)
                
                # Update the sheet with labeling tool data
                update_sheet_from_LT(
                    sheet_name,
                    column_indices,
                    config['project_id']
                )
                
                break  # Success, exit retry loop
                
            except (ConnectionError, gspread.exceptions.APIError) as e:
                is_retryable = isinstance(e, ConnectionError)
                if isinstance(e, gspread.exceptions.APIError):
                    # gspread.exceptions.APIError can be a dict. Let's check safely
                    try:
                        # Heuristic to check for API error structure
                        if 'error' in e.args[0] and e.args[0]['error']['code'] in [429, 500, 503]:
                            is_retryable = True
                    except (AttributeError, IndexError, TypeError):
                        pass

                if is_retryable and attempt < retries - 1:
                    print(colored(f"Connection or API error for sheet '{sheet_name}'. Retrying in {delay}s...", "yellow"))
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    print(colored(f"Failed to process sheet '{sheet_name}' after {retries} attempts: {e}", "red"))
                    break  # Failed after retries, exit retry loop
            
            except gspread.exceptions.SpreadsheetNotFound:
                print(colored(f"Error: Spreadsheet not found. Make sure the key '{get_spreadsheet_key()}' is correct and you have shared the sheet with the service account email.", "red"))
                break
            except gspread.exceptions.WorksheetNotFound:
                print(colored(f"Error: Worksheet '{sheet_name}' not found in the spreadsheet.", "red"))
                break
            except Exception as e:
                print(colored(f"An unexpected error occurred while processing sheet {sheet_name}: {e}", "red"))
                import traceback
                print(colored(f"Full traceback: {traceback.format_exc()}", "red"))
                break
    
    print("\n--- Labeling Tool Data Update Complete ---")

if __name__ == "__main__":
    main() 
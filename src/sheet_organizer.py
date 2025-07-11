import os
import sys
import gspread
import time
import pandas as pd

# Add the src directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config_utils import (
    get_gspread_client,
    get_google_sheet,
    get_all_language_configs,
    get_language_sheet_name
)

def get_destination_sheet_for_language(language: str) -> str:
    """
    Get the destination sheet name for a given language using centralized config.
    
    Args:
        language: Language name (e.g., 'Java', 'JavaScript', etc.)
        
    Returns:
        Sheet name where the language should be placed
    """
    try:
        return get_language_sheet_name(language)
    except (KeyError, FileNotFoundError):
        # Fallback to "Scrap" for unknown languages
        return "Scrap"

def get_all_language_sheet_names():
    """
    Get all unique sheet names from the language configuration.
    
    Returns:
        Set of all sheet names configured for languages
    """
    try:
        all_languages = get_all_language_configs()
        sheet_names = set()
        
        for lang_name, lang_config in all_languages.items():
            sheet_name = lang_config.get('sheet_name', '')
            if sheet_name:
                sheet_names.add(sheet_name)
                # Log Python specifically to verify it's included
                if lang_name == 'Python':
                    print(f"[Config] Python sheet included: '{sheet_name}'")
        
        # Always include Scrap sheet
        sheet_names.add("Scrap")
        
        return sheet_names
    except (FileNotFoundError, KeyError):
        # Fallback to basic set if config not available
        return {"JS/TS", "Java", "Python", "C/C++", "Rust", "C#", "Go", "Ruby", "Scrap"}

# Constants
RATE_LIMIT_SLEEP_SEC = 60  # Wait 60 seconds when quota exceeded
MAX_RETRIES = 5


def safe_gspread_call(func, *args, **kwargs):
    """Wrapper to safely call gspread operations with basic retry on 429 quota errors."""
    for attempt in range(MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "429" in str(e) or "Quota exceeded" in str(e):
                print(f"Quota exceeded. Waiting {RATE_LIMIT_SLEEP_SEC} seconds before retrying (attempt {attempt + 1}/{MAX_RETRIES}) ...")
                time.sleep(RATE_LIMIT_SLEEP_SEC)
                continue
            raise
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries for gspread call {func.__name__}")


def check_repo_exists_in_sheet(client, spreadsheet, sheet_name: str, repo_name: str) -> bool:
    """
    Check if a repository already exists in a specific sheet.
    
    Args:
        client: gspread client
        spreadsheet: gspread spreadsheet object
        sheet_name: Name of the sheet to check
        repo_name: Repository name to look for (Column A)
        
    Returns:
        True if repository exists, False otherwise
    """
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        all_values = safe_gspread_call(worksheet.get_all_values)
        
        if len(all_values) <= 1:  # Only header or empty
            return False
        
        # Check Column A (index 0) for the repository name
        for row in all_values[1:]:  # Skip header
            if row and row[0].strip().lower() == repo_name.strip().lower():
                return True
        
        return False
        
    except Exception as e:
        print(f"Error checking if {repo_name} exists in {sheet_name}: {e}")
        return False


def move_repo_to_sheet(client, spreadsheet, source_sheet: str, target_sheet: str, repo_row_data: list) -> bool:
    """
    Move a repository row from source sheet to target sheet.
    
    Args:
        client: gspread client
        spreadsheet: gspread spreadsheet object
        source_sheet: Name of the source sheet
        target_sheet: Name of the target sheet
        repo_row_data: List containing the row data to move
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Get target worksheet
        target_worksheet = spreadsheet.worksheet(target_sheet)
        
        # Append the row to the target sheet
        safe_gspread_call(target_worksheet.append_row, repo_row_data)
        print(f"Successfully moved {repo_row_data[0]} to {target_sheet}")
        return True
        
    except Exception as e:
        print(f"Error moving {repo_row_data[0] if repo_row_data else 'unknown repo'} to {target_sheet}: {e}")
        return False


def delete_repo_from_sheet(client, spreadsheet, sheet_name: str, repo_name: str) -> bool:
    """
    Delete a repository row from a specific sheet.
    
    Args:
        client: gspread client
        spreadsheet: gspread spreadsheet object
        sheet_name: Name of the sheet to delete from
        repo_name: Repository name to delete (Column A)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        all_values = safe_gspread_call(worksheet.get_all_values)
        
        if len(all_values) <= 1:  # Only header or empty
            return False
        
        # Find the row to delete
        for row_idx, row in enumerate(all_values[1:], start=2):  # Start from row 2 (1-based)
            if row and row[0].strip().lower() == repo_name.strip().lower():
                safe_gspread_call(worksheet.delete_rows, row_idx)
                print(f"Successfully deleted {repo_name} from {sheet_name}")
                return True
        
        print(f"Repository {repo_name} not found in {sheet_name}")
        return False
        
    except Exception as e:
        print(f"Error deleting {repo_name} from {sheet_name}: {e}")
        return False


def process_single_repo_movement(client, spreadsheet, source_sheet: str, repo_name: str, majority_language: str) -> bool:
    """
    Process movement of a single repository based on its majority language.
    
    Args:
        client: gspread client
        spreadsheet: gspread spreadsheet object
        source_sheet: Name of the source sheet
        repo_name: Repository name to process
        majority_language: The majority language detected for this repo
        
    Returns:
        True if repo was moved or deleted, False if no action taken
    """
    target_sheet = get_destination_sheet_for_language(majority_language)
    
    # If the repo should stay in the same sheet, no action needed
    if target_sheet == source_sheet:
        return False
    
    print(f"Processing {repo_name}: {majority_language} -> {target_sheet}")
    
    # Check if repo already exists in target sheet
    if check_repo_exists_in_sheet(client, spreadsheet, target_sheet, repo_name):
        print(f"  {repo_name} already exists in {target_sheet}, deleting from {source_sheet}")
        return delete_repo_from_sheet(client, spreadsheet, source_sheet, repo_name)
    else:
        # Get the row data from source sheet
        try:
            source_worksheet = spreadsheet.worksheet(source_sheet)
            all_values = safe_gspread_call(source_worksheet.get_all_values)
            
            # Find the row to move
            for row_idx, row in enumerate(all_values[1:], start=2):  # Start from row 2 (1-based)
                if row and row[0].strip().lower() == repo_name.strip().lower():
                    # Move the row to target sheet
                    if move_repo_to_sheet(client, spreadsheet, source_sheet, target_sheet, row):
                        # Delete from source sheet
                        return delete_repo_from_sheet(client, spreadsheet, source_sheet, repo_name)
                    break
            
            print(f"Repository {repo_name} not found in {source_sheet}")
            return False
            
        except Exception as e:
            print(f"Error processing movement for {repo_name}: {e}")
            return False


def remove_duplicates_within_sheet(client, spreadsheet, sheet_name):
    """
    Remove duplicate repositories within a single sheet.
    Keeps the first occurrence and removes all subsequent duplicates.
    Deletes from bottom to top to avoid index shifting issues.
    
    Args:
        client: gspread client
        spreadsheet: gspread spreadsheet object
        sheet_name: Name of the sheet to check for duplicates
        
    Returns:
        Number of duplicates removed
    """
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        
        # Get all values from the sheet
        all_values = safe_gspread_call(worksheet.get_all_values)
        
        if len(all_values) <= 1:  # Only header or empty
            print(f"Sheet {sheet_name} has no data rows to check for duplicates")
            return 0
        
        # Convert to DataFrame for easier duplicate detection
        df = pd.DataFrame(all_values[1:], columns=all_values[0])
        
        if df.empty or len(df.columns) == 0:
            print(f"Sheet {sheet_name} has no valid data to check for duplicates")
            return 0
        
        # Check for duplicates in Column A (repository names)
        repo_col = df.iloc[:, 0]  # First column (repository names)
        
        # Find duplicates - mark all occurrences except the first as True
        duplicate_mask = repo_col.duplicated(keep='first')
        
        # Get indices of duplicate rows (convert to 1-based sheet row numbers)
        duplicate_indices = []
        for idx, is_duplicate in enumerate(duplicate_mask):
            if is_duplicate:
                sheet_row = idx + 2  # +2 because: +1 for header, +1 for 1-based indexing
                repo_name = repo_col.iloc[idx]
                duplicate_indices.append((sheet_row, repo_name))
        
        if not duplicate_indices:
            print(f"No duplicates found in sheet {sheet_name}")
            return 0
        
        print(f"Found {len(duplicate_indices)} duplicates in sheet {sheet_name}")
        
        # Sort indices in descending order to delete from bottom to top
        duplicate_indices.sort(reverse=True)
        
        # Delete duplicate rows
        deleted_count = 0
        for sheet_row, repo_name in duplicate_indices:
            try:
                print(f"  Deleting duplicate: {repo_name} from row {sheet_row}")
                safe_gspread_call(worksheet.delete_rows, sheet_row)
                deleted_count += 1
            except Exception as e:
                print(f"  Error deleting duplicate {repo_name} from row {sheet_row}: {e}")
        
        print(f"Successfully removed {deleted_count} duplicates from sheet {sheet_name}")
        return deleted_count
        
    except Exception as e:
        print(f"Error removing duplicates from sheet {sheet_name}: {e}")
        return 0


def organize_sheets():
    """
    Organizes repositories in Google Sheets based on their majority language.
    First removes duplicates within each sheet, then moves repos based on language.
    Uses DataFrames for all operations and minimizes sheet API calls.
    """
    print("Starting sheet organization process...")

    # Define the sheets we're working with
    SHEETS = get_all_language_sheet_names()

    try:
        # Get Google Sheets client and spreadsheet
        client = get_gspread_client()
        spreadsheet = get_google_sheet(client)
        
        print(f"Connected to spreadsheet: {spreadsheet.title}")
        
        # STEP 1: Remove duplicates within each sheet first
        print(f"\n{'='*60}")
        print("STEP 1: REMOVING DUPLICATES WITHIN SHEETS")
        print(f"{'='*60}")
        
        total_duplicates_removed = 0
        for sheet_name in SHEETS:
            if sheet_name == "Scrap":
                continue  # Skip Scrap sheet for duplicate removal
                
            print(f"\nChecking for duplicates in sheet: {sheet_name}")
            try:
                duplicates_removed = remove_duplicates_within_sheet(client, spreadsheet, sheet_name)
                total_duplicates_removed += duplicates_removed
            except Exception as e:
                print(f"Error checking duplicates in sheet {sheet_name}: {e}")
                continue
        
        print(f"\n📊 DUPLICATE REMOVAL SUMMARY:")
        print(f"   🗑️  Total duplicates removed: {total_duplicates_removed}")
        
        # STEP 2: Process each sheet for language-based organization
        print(f"\n{'='*60}")
        print("STEP 2: LANGUAGE-BASED ORGANIZATION")
        print(f"{'='*60}")
        
        for sheet_name in SHEETS:
            if sheet_name == "Scrap":
                continue  # Skip Scrap sheet as source
                
            print(f"\nProcessing sheet: {sheet_name}")
            
            try:
                worksheet = spreadsheet.worksheet(sheet_name)
                
                # Get all values from the sheet and convert to DataFrame
                all_values = safe_gspread_call(worksheet.get_all_values)
                
                if len(all_values) <= 1:  # Only header or empty
                    print(f"Sheet {sheet_name} is empty or has only header. Skipping.")
                    continue
                
                # Convert to DataFrame
                df = pd.DataFrame(all_values[1:], columns=all_values[0])
                
                # Check if 'Majority Language' column exists
                if 'Majority Language' not in df.columns:
                    print(f"Column 'Majority Language' not found in sheet {sheet_name}. Skipping.")
                    continue
                
                # Filter out empty/N/A majority language entries
                df_filtered = df[
                    (df['Majority Language'].str.strip() != '') &
                    (df['Majority Language'].str.upper() != 'N/A') &
                    (df['Majority Language'].str.upper() != 'NA') &
                    (df['Majority Language'].notna())
                ].copy()
                
                if df_filtered.empty:
                    print(f"No valid rows to process in {sheet_name}")
                    continue
                
                # Get unique languages in this sheet
                unique_languages = df_filtered['Majority Language'].str.strip().unique()
                print(f"Found languages in {sheet_name}: {list(unique_languages)}")
                
                # Process each language in this sheet
                for language in unique_languages:
                    destination_sheet = get_destination_sheet_for_language(language)
                    
                    if destination_sheet == sheet_name:
                        print(f"  Language {language} already in correct sheet {sheet_name}. Skipping.")
                        continue
                    
                    print(f"  Processing language: {language} -> {destination_sheet}")
                    
                    # REFRESH DATA - Get current state after previous language processing
                    all_values = safe_gspread_call(worksheet.get_all_values)
                    
                    if len(all_values) <= 1:  # Only header or empty after deletions
                        print(f"    Sheet {sheet_name} is now empty. Moving to next language.")
                        continue
                    
                    # Convert fresh data to DataFrame
                    df = pd.DataFrame(all_values[1:], columns=all_values[0])
                    
                    # Filter out empty/N/A majority language entries
                    df_filtered = df[
                        (df['Majority Language'].str.strip() != '') &
                        (df['Majority Language'].str.upper() != 'N/A') &
                        (df['Majority Language'].str.upper() != 'NA') &
                        (df['Majority Language'].notna())
                    ].copy()
                    
                    # Get all rows for this language
                    language_rows = df_filtered[df_filtered['Majority Language'].str.strip() == language].copy()
                    
                    if language_rows.empty:
                        print(f"    No rows found for language {language}")
                        continue
                    
                    print(f"    Found {len(language_rows)} rows for language {language}")
                    
                    # Get destination worksheet and convert to DataFrame
                    dest_worksheet = spreadsheet.worksheet(destination_sheet)
                    dest_all_values = safe_gspread_call(dest_worksheet.get_all_values)
                    
                    existing_repos = set()
                    if len(dest_all_values) > 1:  # Has data beyond header
                        dest_df = pd.DataFrame(dest_all_values[1:], columns=dest_all_values[0])
                        if not dest_df.empty and len(dest_df.columns) > 0:
                            existing_repos = set(dest_df.iloc[:, 0].tolist())  # Column A (repo names)
                    
                    # Filter out duplicates using DataFrame operations
                    repo_col = language_rows.iloc[:, 0]  # Column A (repo names)
                    duplicates_mask = repo_col.isin(existing_repos)
                    
                    rows_to_move = language_rows[~duplicates_mask]
                    rows_to_delete_only = language_rows[duplicates_mask]
                    
                    print(f"    Duplicates to delete: {len(rows_to_delete_only)}")
                    print(f"    Rows to move: {len(rows_to_move)}")
                    
                    # Log duplicates
                    if not rows_to_delete_only.empty:
                        for _, row in rows_to_delete_only.iterrows():
                            print(f"      Duplicate: {row.iloc[0]}")
                    
                    # Log rows to move
                    if not rows_to_move.empty:
                        for _, row in rows_to_move.iterrows():
                            print(f"      Will move: {row.iloc[0]}")
                    
                    # BULK APPEND to destination (if there are rows to move)
                    if not rows_to_move.empty:
                        print(f"    Bulk appending {len(rows_to_move)} rows to {destination_sheet}")
                        try:
                            # Convert DataFrame to list of lists for bulk append
                            rows_to_append = rows_to_move.values.tolist()
                            safe_gspread_call(dest_worksheet.append_rows, rows_to_append)
                            print(f"      Successfully bulk appended {len(rows_to_append)} rows to {destination_sheet}")
                        except Exception as e:
                            print(f"      ERROR: Could not bulk append to {destination_sheet}: {e}")
                            continue
                    
                    # BULK DELETE from source (both moved rows and duplicates)
                    all_rows_to_delete = pd.concat([rows_to_move, rows_to_delete_only]) if not rows_to_delete_only.empty else rows_to_move
                    
                    if not all_rows_to_delete.empty:
                        print(f"    Bulk deleting {len(all_rows_to_delete)} rows from {sheet_name}")
                        
                        # Get fresh data again to find current row indices
                        fresh_values = safe_gspread_call(worksheet.get_all_values)
                        fresh_df = pd.DataFrame(fresh_values[1:], columns=fresh_values[0])
                        
                        # Find row indices to delete (from bottom to top)
                        indices_to_delete = []
                        for _, row_to_delete in all_rows_to_delete.iterrows():
                            repo_name = row_to_delete.iloc[0]
                            # Find matching rows in fresh data
                            matches = fresh_df[fresh_df.iloc[:, 0] == repo_name]
                            if not matches.empty:
                                # Get the first match index (1-based for gspread) - convert to regular int
                                idx = int(matches.index[0]) + 2  # +2 for header and 1-based indexing
                                indices_to_delete.append((idx, repo_name))
                        
                        # Sort indices in descending order for safe deletion
                        indices_to_delete.sort(reverse=True)
                        
                        # Delete rows one by one (still need individual deletes due to gspread limitations)
                        for idx, repo_name in indices_to_delete:
                            try:
                                safe_gspread_call(worksheet.delete_rows, idx)
                                action = "moved" if repo_name in rows_to_move.iloc[:, 0].values else "deleted duplicate"
                                print(f"      Successfully {action}: {repo_name} (row {idx})")
                            except Exception as e:
                                print(f"      ERROR: Could not delete {repo_name} from {sheet_name} (row {idx}): {e}")
                    
                    print(f"    Completed processing language {language}")
                
                print(f"Completed processing sheet: {sheet_name}")
                
            except Exception as e:
                print(f"Error processing sheet {sheet_name}: {e}")
                continue
        
        print("\nSheet organization process completed!")
        
    except Exception as e:
        print(f"Error connecting to Google Sheets: {e}")


if __name__ == "__main__":
    organize_sheets() 
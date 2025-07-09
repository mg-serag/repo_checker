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
)

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


def organize_sheets():
    """
    Organizes repositories in Google Sheets based on their majority language.
    Uses DataFrames for all operations and minimizes sheet API calls.
    """
    print("Starting sheet organization process...")

    # Define the sheets we're working with
    SHEETS = ["JS/TS", "Java", "C/C++", "Rust", "C#", "Go", "Scrap"]
    
    # Language to sheet mapping
    LANGUAGE_TO_SHEET = {
        "JavaScript": "JS/TS",
        "TypeScript": "JS/TS", 
        "Java": "Java",
        "C": "C/C++",
        "C++": "C/C++",
        "Rust": "Rust",
        "C#": "C#",
        "Go": "Go"
    }

    try:
        # Get Google Sheets client and spreadsheet
        client = get_gspread_client()
        spreadsheet = get_google_sheet(client)
        
        print(f"Connected to spreadsheet: {spreadsheet.title}")
        
        # Process each sheet
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
                    destination_sheet = LANGUAGE_TO_SHEET.get(language, "Scrap")
                    
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
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread_formatting import *

# --- Constants ---
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
SHEET_ID = '1yRoHc_y5cn_IsvYdRG8bxSPONpuXEDRJ_XCdfxkbmgY'
SHEET_NAME = 'Trainers repositories'
CREDS_FILE = 'repo_evaluator/creds.json'

# --- Environment Variables ---
# No environment variables needed for this script if creds.json is used.

def authenticate_google_sheets():
    """Authenticates with Google Sheets API using a local credentials file."""
    if not os.path.exists(CREDS_FILE):
        raise FileNotFoundError(f"Credentials file not found at '{CREDS_FILE}'.")
    
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPES)
    client = gspread.authorize(creds)
    return client

def apply_formatting(worksheet):
    """Applies hardcoded and dynamic background color formatting."""
    print("Applying formatting...")

    # Define color formats
    light_blue = CellFormat(backgroundColor=Color(0.81, 0.89, 0.95))  # #cfe2f3
    light_yellow = CellFormat(backgroundColor=Color(1.0, 0.95, 0.8))   # #fff2cc

    # Hardcoded formatting rules
    hardcoded_ranges = [
        ('I1:K220', light_blue),
        ('I221:K497', light_yellow),
        ('I498:K525', light_blue),
        ('I526:K650', light_yellow),
    ]

    for range_str, cell_format in hardcoded_ranges:
        print(f"Formatting range {range_str}...")
        format_cell_range(worksheet, range_str, cell_format)

    # Dynamic formatting
    print("Applying dynamic formatting...")
    
    try:
        all_values = worksheet.get_all_values()

        # Determine first uncoloured row – we assume rows 1-650 are already coloured
        # Find the last colored row by checking for existing formatting
        first_row = 651  # Default fallback
        try:
            # Get the current formatting to find the last colored row
            # We'll check column I formatting as a proxy for the last colored row
            col_i_formatting = worksheet.get(f'I1:I{first_row-1}')
            
            # Find the last row that has background color formatting
            last_colored_row = 0
            for row_num in range(1, first_row):
                cell_address = f'I{row_num}'
                try:
                    cell_format = worksheet.get(cell_address)
                    # Check if cell has background color formatting
                    if hasattr(cell_format, 'backgroundColor') and cell_format.backgroundColor:
                        last_colored_row = row_num
                except:
                    continue
            
            # Set first_row to be the next row after the last colored row
            if last_colored_row > 0:
                first_row = last_colored_row + 1
                print(f"Found last colored row: {last_colored_row}, starting dynamic formatting from row: {first_row}")
            else:
                print(f"No existing formatting found, using default first_row: {first_row}")
                
        except Exception as e:
            print(f"Error determining last colored row, using default first_row {first_row}: {e}")

        # Determine last row based on the last non-empty value in column H (index 7)  
        col_h_values = worksheet.col_values(8)  # Column H is 8 (1-indexed)
        last_row = len(col_h_values)
        if last_row < first_row:
            print("No rows needing dynamic colouring.")
            return

        # Slice the cached sheet data for rows in [first_row, last_row]
        col_i_values = []
        for r in range(first_row-1, last_row):  # zero-based indexing
            row = all_values[r] if r < len(all_values) else []
            col_i_values.append(row[8] if len(row) > 8 else '')

        yes_indices = []
        for i, value in enumerate(col_i_values, start=651):
            if str(value).strip().lower() == 'yes':
                yes_indices.append(i)

        if len(yes_indices) < 2:
            print("Not enough 'Yes' values found after row 650 to create two dynamic groups. Skipping.")
            return

        midpoint_index = len(yes_indices) // 2
        split_row = yes_indices[midpoint_index - 1]

        # First dynamic group
        range1 = f'I{first_row}:K{split_row}'
        print(f"Formatting range {range1} with light blue...")
        format_cell_range(worksheet, range1, light_blue)

        # Second dynamic group
        if split_row < last_row:
            range2 = f'I{split_row + 1}:K{last_row}'
            print(f"Formatting range {range2} with light yellow...")
            format_cell_range(worksheet, range2, light_yellow)
        
        print("Dynamic formatting applied successfully.")

    except IndexError:
        print("Could not find column I. Please ensure the sheet has at least 9 columns (A-I).")
    except Exception as e:
        print(f"An error occurred during dynamic formatting: {e}")


def main():
    """Main function to run the script."""
    try:
        gsheet_client = authenticate_google_sheets()
        sheet = gsheet_client.open_by_key(SHEET_ID)
        worksheet = sheet.worksheet(SHEET_NAME)
        
        apply_formatting(worksheet)
        
        print("\nFormatting complete.")

    except ValueError as e:
        print(f"Configuration error: {e}")
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"Spreadsheet with ID '{SHEET_ID}' not found.")
    except gspread.exceptions.WorksheetNotFound:
        print(f"Worksheet with name '{SHEET_NAME}' not found in the spreadsheet.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == '__main__':
    main() 
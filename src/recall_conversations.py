#!/usr/bin/env python3
"""
Conversation Recall Script

This script reads conversation IDs from a CSV file and fetches their metadata
from the labeling tool, producing a cleaned CSV output similar to convert.py.

Usage:
    python recall_conversations.py input.csv output.csv
    python recall_conversations.py --input input.csv --output output.csv --project-id 42
"""

import csv
import json
import os
import requests
import argparse
from datetime import datetime
import pandas as pd

# Import configuration
from config_utils import get_lt_token

# Configuration
LT_TOKEN = get_lt_token()
BASE_CONVERSATIONS_URL = "https://eval.turing.com/api/conversations"
DEFAULT_PROJECT_ID = 42  # Java project as specified

def clean_metadata(obj):
    """
    Remove specified fields from metadata object to reduce file size.
    Uses the same cleaning logic as convert.py.
    """
    fields_to_remove = [
        'patch',
        'test_patch',
        'agent_patch',
        'FAIL_TO_PASS',
        'PASS_TO_PASS',
        'test_output_before',
        'errors_before',
        'failed_before',
        'test_output_after',
        'errors_after',
        'failed_after'
    ]
    
    # Create a copy of the object to avoid modifying the original
    cleaned_obj = obj.copy()
    
    # Remove specified fields
    for field in fields_to_remove:
        cleaned_obj.pop(field, None)
    
    return cleaned_obj

def fetch_conversation_by_id(conversation_id, project_id=None):
    """
    Fetch a single conversation by its ID from the labeling tool.
    
    Args:
        conversation_id: The conversation ID to fetch
        project_id: Optional project ID filter
        
    Returns:
        Conversation data or None if not found/error
    """
    headers = {"Authorization": f"Bearer {LT_TOKEN}"}
    
    try:
        # Construct URL for specific conversation
        url = f"{BASE_CONVERSATIONS_URL}/{conversation_id}"
        
        # Add project filter if specified
        if project_id:
            url += f"?join%5B0%5D=project%7C%7Cid%2Cname&join%5B1%5D=batch%7C%7Cid%2Cname&join%5B2%5D=seed%7C%7Cmetadata&filter%5B0%5D=projectId%7C%7C%24eq%7C%7C{project_id}"
        else:
            url += "?join%5B0%5D=project%7C%7Cid%2Cname&join%5B1%5D=batch%7C%7Cid%2Cname&join%5B2%5D=seed%7C%7Cmetadata"
        
        print(f"  Fetching conversation {conversation_id}...")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        conversation_data = response.json()
        return conversation_data
        
    except requests.exceptions.RequestException as e:
        print(f"  Error fetching conversation {conversation_id}: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"  Error parsing JSON for conversation {conversation_id}: {e}")
        return None

def read_conversation_ids_from_csv(input_file):
    """
    Read conversation IDs from a CSV file.
    
    Args:
        input_file: Path to the input CSV file
        
    Returns:
        List of conversation IDs
    """
    conversation_ids = []
    
    try:
        with open(input_file, 'r', encoding='utf-8') as csvfile:
            # Try to detect if file has headers
            sample = csvfile.read(1024)
            csvfile.seek(0)
            sniffer = csv.Sniffer()
            has_header = sniffer.has_header(sample)
            
            reader = csv.reader(csvfile)
            
            if has_header:
                header = next(reader)
                print(f"CSV headers detected: {header}")
                
                # Find the Id column (case-insensitive)
                id_col_index = None
                for i, col_name in enumerate(header):
                    if col_name.lower() in ['id', 'conversation_id', 'conv_id']:
                        id_col_index = i
                        print(f"Using column '{col_name}' (index {i}) for conversation IDs")
                        break
                
                if id_col_index is None:
                    print("Warning: No 'Id' column found. Using first column.")
                    id_col_index = 0
            else:
                print("No headers detected. Using first column for conversation IDs.")
                id_col_index = 0
            
            # Read conversation IDs
            for row_num, row in enumerate(reader, start=2 if has_header else 1):
                if row and len(row) > id_col_index:
                    conv_id = row[id_col_index].strip()
                    if conv_id and conv_id.isdigit():
                        conversation_ids.append(conv_id)
                    elif conv_id:
                        print(f"Warning: Invalid conversation ID '{conv_id}' on row {row_num}")
    
    except FileNotFoundError:
        print(f"Error: Input file '{input_file}' not found.")
        return []
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return []
    
    print(f"Found {len(conversation_ids)} conversation IDs to process")
    return conversation_ids

def write_conversations_to_csv(conversations_data, output_file):
    """
    Write conversation metadata to CSV file.
    
    Args:
        conversations_data: List of conversation data dictionaries
        output_file: Path to the output CSV file
    """
    try:
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write header
            writer.writerow(['conversation_id', 'project_id', 'batch_id', 'batch_name', 'metadata'])
            
            # Write data rows
            for conv_data in conversations_data:
                if conv_data is None:
                    continue
                
                conversation_id = conv_data.get('id', '')
                project_id = conv_data.get('project', {}).get('id', '') if conv_data.get('project') else ''
                batch_id = conv_data.get('batch', {}).get('id', '') if conv_data.get('batch') else ''
                batch_name = conv_data.get('batch', {}).get('name', '') if conv_data.get('batch') else ''
                
                # Get and clean metadata
                metadata = conv_data.get('seed', {}).get('metadata', {})
                if metadata:
                    cleaned_metadata = clean_metadata(metadata)
                    metadata_json = json.dumps(cleaned_metadata)
                else:
                    metadata_json = ''
                
                writer.writerow([conversation_id, project_id, batch_id, batch_name, metadata_json])
        
        print(f"Successfully wrote {len(conversations_data)} conversations to {output_file}")
        
    except Exception as e:
        print(f"Error writing to CSV file: {e}")

def process_conversations(input_file, output_file, project_id=None):
    """
    Main processing function to read IDs, fetch conversations, and write output.
    
    Args:
        input_file: Path to input CSV with conversation IDs
        output_file: Path to output CSV file
        project_id: Optional project ID filter
    """
    print("=" * 60)
    print("CONVERSATION RECALL SCRIPT")
    print("=" * 60)
    print(f"Input file: {input_file}")
    print(f"Output file: {output_file}")
    print(f"Project ID filter: {project_id if project_id else 'None (all projects)'}")
    print("=" * 60)
    
    # Read conversation IDs from input CSV
    conversation_ids = read_conversation_ids_from_csv(input_file)
    
    if not conversation_ids:
        print("No valid conversation IDs found. Exiting.")
        return
    
    # Fetch conversations from labeling tool
    print(f"\nFetching {len(conversation_ids)} conversations from labeling tool...")
    conversations_data = []
    successful_fetches = 0
    failed_fetches = 0
    
    for i, conv_id in enumerate(conversation_ids, 1):
        print(f"Progress: {i}/{len(conversation_ids)}")
        
        conv_data = fetch_conversation_by_id(conv_id, project_id)
        if conv_data:
            conversations_data.append(conv_data)
            successful_fetches += 1
        else:
            failed_fetches += 1
            # Add placeholder for failed fetches to maintain order
            conversations_data.append(None)
    
    print(f"\nFetch Summary:")
    print(f"  Successful: {successful_fetches}")
    print(f"  Failed: {failed_fetches}")
    print(f"  Total: {len(conversation_ids)}")
    
    # Write results to output CSV
    if conversations_data:
        print(f"\nWriting results to {output_file}...")
        write_conversations_to_csv(conversations_data, output_file)
        print("✅ Process completed successfully!")
    else:
        print("❌ No conversation data to write.")

def main():
    """Main function with command line argument parsing."""
    parser = argparse.ArgumentParser(
        description="Fetch conversation metadata from labeling tool based on conversation IDs in CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python recall_conversations.py input.csv output.csv
  python recall_conversations.py --input conversations.csv --output metadata.csv
  python recall_conversations.py --input conversations.csv --output metadata.csv --project-id 42
        """
    )
    
    parser.add_argument('input_file', nargs='?', help='Input CSV file with conversation IDs')
    parser.add_argument('output_file', nargs='?', help='Output CSV file for metadata')
    parser.add_argument('--input', '-i', dest='input_file_flag', help='Input CSV file with conversation IDs')
    parser.add_argument('--output', '-o', dest='output_file_flag', help='Output CSV file for metadata')
    parser.add_argument('--project-id', '-p', type=int, default=DEFAULT_PROJECT_ID, 
                       help=f'Project ID filter (default: {DEFAULT_PROJECT_ID})')
    
    args = parser.parse_args()
    
    # Handle input file
    input_file = args.input_file or args.input_file_flag
    if not input_file:
        print("Error: Input file is required.")
        parser.print_help()
        return
    
    # Handle output file
    output_file = args.output_file or args.output_file_flag
    if not output_file:
        # Generate default output filename
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = f"{base_name}_metadata.csv"
        print(f"No output file specified. Using: {output_file}")
    
    # Validate input file exists
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' does not exist.")
        return
    
    # Process conversations
    try:
        process_conversations(input_file, output_file, args.project_id)
    except KeyboardInterrupt:
        print("\n❌ Process interrupted by user.")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Direct execution with specified input file
    input_file = "src/convo_input.csv"
    output_file = "src/convo_output.csv"
    project_id = DEFAULT_PROJECT_ID  # Uses 42 (Java project)
    
    try:
        process_conversations(input_file, output_file, project_id)
    except KeyboardInterrupt:
        print("\n❌ Process interrupted by user.")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    
    # Uncomment the line below if you want to use command line arguments instead
    # main() 
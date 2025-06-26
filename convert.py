#!/usr/bin/env python3
import json
import csv
import os
import requests
import argparse
from datetime import datetime
from pathlib import Path

# Default input and output paths
DEFAULT_INPUT_DIR = "json"
DEFAULT_OUTPUT_DIR = "csv"
FILTER_DATE = datetime(2024, 11, 1)

LANGUAGE_JSON_SUFFIX = "_json"
LANGUAGE_CSV_SUFFIX = "_csv"

# LT API Configuration
LT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Im1vaGFtYWQuc0B0dXJpbmcuY29tIiwic3ViIjoxMTYsImlhdCI6MTc1MDc0NzY0MywiZXhwIjoxNzUxMzUyNDQzfQ.De_PSAqQl306vqf7BEFIYbjo66zehS8coPtUEfZhk8w"
BASE_BATCHES_URL = "https://eval.turing.com/api/batches?sort%5B0%5D=createdAt%2CDESC&join%5B0%5D=batchStats&join%5B1%5D=importAttempts"
BASE_CONVERSATIONS_URL = "https://eval.turing.com/api/conversations?join%5B0%5D=project%7C%7Cid%2Cname&join%5B1%5D=batch%7C%7Cid%2Cname&join%5B2%5D=seed%7C%7Cmetadata"

def fetch_existing_repos_for_project(project_id):
    """Fetches all batch data from the API for a specific project by handling pagination."""
    headers = {"Authorization": f"Bearer {LT_TOKEN}"}
    all_batches = []
    page = 1
    limit = 100
    
    # Add project filter to the URL
    project_filter = f"&filter%5B0%5D=projectId%7C%7C%24eq%7C%7C{project_id}"
    base_url = f"{BASE_BATCHES_URL}{project_filter}"

    while True:
        paginated_url = f"{base_url}&limit={limit}&page={page}"
        print(f"    Fetching batches from page {page} for project {project_id}...")
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
            print(f"    An error occurred while fetching batches on page {page} for project {project_id}: {e}")
            return None
    return {"data": all_batches}

def fetch_conversations_for_batch(batch_id):
    """Fetches all conversations for a specific batch ID."""
    headers = {"Authorization": f"Bearer {LT_TOKEN}"}
    all_conversations = []
    page = 1
    limit = 100

    while True:
        filter_param = f"&filter%5B0%5D=batchId%7C%7C%24in%7C%7C{batch_id}"
        paginated_url = f"{BASE_CONVERSATIONS_URL}{filter_param}&limit={limit}&page={page}"
        print(f"  Fetching conversations for batch {batch_id}, page {page}...")
        try:
            response = requests.get(paginated_url, headers=headers)
            response.raise_for_status()
            json_data = response.json()
            conversations_on_page = json_data.get("data")
            if not conversations_on_page:
                break
            all_conversations.extend(conversations_on_page)
            if len(conversations_on_page) < limit:
                break
            page += 1
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while fetching conversations for batch {batch_id}: {e}")
            return None
    return all_conversations

def get_existing_repos_set():
    """Fetches all existing repository names from the labeling tool for all projects (40-43)."""
    print("Fetching existing repository names from labeling tool for all projects...")
    existing_repos = set()
    
    # Get all repositories from all projects
    for project_id in range(40, 44):
        print(f"\nProcessing project ID: {project_id}")
        try:
            repo_data = fetch_existing_repos_for_project(project_id)
        except Exception as e:
            print(f"Error fetching repositories for project {project_id}: {e}")
            continue
        
        if not repo_data or not repo_data.get("data"):
            print(f"No repository data received for project {project_id}.")
            continue
        
        # Collect all repository names
        for batch in repo_data["data"]:
            repo_name = batch.get("name", "Unknown")
            if repo_name != "Unknown":
                existing_repos.add(repo_name)
                print(f"  Found repo: {repo_name}")
    
    print(f"\nFound {len(existing_repos)} total repositories across all projects")
    return existing_repos

def check_repo_exists_in_lt(repo_name):
    """Check if a repository exists in the labeling tool across all projects (40-43)."""
    print(f"Checking if repo {repo_name} exists in labeling tool across all projects...")
    
    # Convert repo name to LT format (USER/REPO -> USER__REPO)
    lt_repo_name = convert_repo_name_to_lt_format(repo_name)
    
    # Check all projects from 40 to 43
    for project_id in range(40, 44):
        print(f"  Checking project ID: {project_id}")
        try:
            repo_data = fetch_existing_repos_for_project(project_id)
        except Exception as e:
            print(f"    Error fetching repositories for project {project_id}: {e}")
            continue
        
        if not repo_data or not repo_data.get("data"):
            continue
        
        for batch in repo_data["data"]:
            batch_name = batch.get("name", "Unknown")
            if batch_name == lt_repo_name:
                print(f"    Found existing repo: {batch_name} in project {project_id}")
                return True
    
    print(f"Repo {repo_name} not found in any project in labeling tool")
    return False

def convert_repo_name_to_lt_format(repo_name):
    """Convert USER/REPO format to USER__REPO format for LT comparison."""
    return repo_name.replace("/", "__")

def get_existing_pr_ids_for_repo(repo_name):
    """Fetches existing PR IDs for a specific repository from the labeling tool."""
    print(f"Fetching existing PR IDs for repo: {repo_name}")
    
    # Convert repo name to LT format (USER/REPO -> USER__REPO)
    lt_repo_name = convert_repo_name_to_lt_format(repo_name)
    existing_pr_ids = set()
    
    # Check all projects from 40 to 43
    for project_id in range(40, 44):
        print(f"  Checking project ID: {project_id}")
        try:
            repo_data = fetch_existing_repos_for_project(project_id)
        except Exception as e:
            print(f"    Error fetching repositories for project {project_id}: {e}")
            continue
        
        if not repo_data or not repo_data.get("data"):
            continue
        
        for batch in repo_data["data"]:
            batch_name = batch.get("name", "Unknown")
            batch_id = batch.get("id")
            
            if batch_name == lt_repo_name and batch_id:
                print(f"    Found repo {batch_name} in project {project_id}, fetching PRs...")
                try:
                    conversations = fetch_conversations_for_batch(batch_id)
                except Exception as e:
                    print(f"      Error fetching conversations for batch {batch_id}: {e}")
                    continue
                
                if conversations:
                    for conv in conversations:
                        pr_id = conv.get("seed", {}).get("metadata", {}).get("pr_id")
                        if pr_id:
                            existing_pr_ids.add(str(pr_id))
    
    print(f"Found {len(existing_pr_ids)} existing PR IDs for repo {repo_name}")
    return existing_pr_ids

def process_json_file(input_file, output_file, existing_repos=None, force=False):
    """Process a single JSON file and convert it to CSV with date filtering and optimized duplicate detection."""
    # Check if output file already exists
    if os.path.exists(output_file) and not force:
        print(f"Skipping {input_file} - {output_file} already exists")
        return False
    
    # Open and load the JSON data from file
    with open(input_file, 'r', encoding='utf-8') as json_file:
        data = json.load(json_file)

    # Ensure that the JSON data is a list of objects
    if not isinstance(data, list):
        raise ValueError(f"The JSON file {input_file} does not contain an array of objects.")

    # Extract repo name from the first object if available
    repo_name = None
    if data and len(data) > 0:
        first_obj = data[0]
        if "repo" in first_obj:
            repo_name = first_obj["repo"]
            print(f"Processing repo: {repo_name}")

    # Filter data based on pr_merged_at date
    filtered_data = []
    for obj in data:
        if "pr_merged_at" in obj:
            try:
                merged_date = datetime.strptime(obj["pr_merged_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
                if merged_date >= FILTER_DATE:
                    filtered_data.append(obj)
            except (ValueError, TypeError):
                continue

    # Create output directory if it doesn't exist
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Write the filtered data to a CSV file
    with open(output_file, 'w', newline='', encoding='utf-8') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(['metadata'])
        for obj in filtered_data:
            json_str = json.dumps(obj)
            writer.writerow([json_str])
    
    # If duplicate detection is enabled and repo name is available
    if existing_repos is not None and repo_name:
        # Convert repo name to LT format for comparison
        lt_repo_name = convert_repo_name_to_lt_format(repo_name)
        
        # Check if repo exists in the labeling tool
        if lt_repo_name in existing_repos:
            print(f"Repo {repo_name} exists in labeling tool, fetching existing PRs...")
            existing_pr_ids = get_existing_pr_ids_for_repo(repo_name)
            
            # Filter out existing PRs
            original_count = len(filtered_data)
            non_existing_data = [obj for obj in filtered_data if str(obj.get("pr_id", "")) not in existing_pr_ids]
            filtered_count = len(non_existing_data)
            print(f"Filtered out {original_count - filtered_count} existing PRs, {filtered_count} remaining")
            
            # Create _part_02 file
            output_dir = os.path.dirname(output_file)
            base_name = os.path.splitext(os.path.basename(output_file))[0]
            part_02_file = os.path.join(output_dir, f"{base_name}_part_02.csv")
            
            with open(part_02_file, 'w', newline='', encoding='utf-8') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(['metadata'])
                for obj in non_existing_data:
                    json_str = json.dumps(obj)
                    writer.writerow([json_str])
            
            print(f"Created _part_02 file: {part_02_file} with {filtered_count} non-existing PRs")
        else:
            print(f"Repo {repo_name} not found in labeling tool, no duplicates to filter")
            # Create _part_02 file with all data since repo doesn't exist
            output_dir = os.path.dirname(output_file)
            base_name = os.path.splitext(os.path.basename(output_file))[0]
            part_02_file = os.path.join(output_dir, f"{base_name}_part_02.csv")
            
            with open(part_02_file, 'w', newline='', encoding='utf-8') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(['metadata'])
                for obj in filtered_data:
                    json_str = json.dumps(obj)
                    writer.writerow([json_str])
            
            print(f"Created _part_02 file: {part_02_file} with all {len(filtered_data)} PRs (repo not in labeling tool)")
    
    return True

def process_directory(input_dir, output_dir, existing_repos=None, force=False):
    """Process all JSON files in a directory."""
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Process each JSON file in the input directory
    for filename in os.listdir(input_dir):
        if filename.endswith('.json'):
            input_path = os.path.join(input_dir, filename)
            
            # Remove "_pr" suffix from filename if present
            base_name = os.path.splitext(filename)[0]
            if base_name.endswith('_pr'):
                base_name = base_name[:-3]
            
            output_path = os.path.join(output_dir, f"{base_name}.csv")
            
            try:
                success = process_json_file(input_path, output_path, existing_repos, force)
                if success:
                    print(f"Successfully converted {input_path} to {output_path}")
            except Exception as e:
                print(f"Error processing {input_path}: {e}")

def process_language_directories(base_dir, json_suffix=LANGUAGE_JSON_SUFFIX, csv_suffix=LANGUAGE_CSV_SUFFIX, existing_repos=None, force=False):
    """Detect and process all *<language>_json directories within base_dir.

    For each directory that matches the pattern, a corresponding *<language>_csv directory
    is created (if necessary) and populated using the existing processing logic.

    Parameters
    ----------
    base_dir : str | Path
        The directory in which to search for language-scoped JSON folders.
    json_suffix : str, optional
        Suffix that denotes a JSON folder for a particular language. Defaults to "_json".
    csv_suffix : str, optional
        Suffix that denotes a CSV output folder. Defaults to "_csv".
    existing_repos : set, optional
        Set of existing repository names to check for duplicates.
    force : bool, optional
        Force processing even if output files already exist.

    Returns
    -------
    bool
        True if at least one language directory was processed, False otherwise.
    """
    processed_any = False
    for entry in os.listdir(base_dir):
        if entry.endswith(json_suffix):
            input_dir = os.path.join(base_dir, entry)
            if not os.path.isdir(input_dir):
                continue  # Skip if not a directory

            # Derive corresponding CSV directory name by swapping suffixes
            output_dir_name = entry.replace(json_suffix, csv_suffix)
            output_dir = os.path.join(base_dir, output_dir_name)

            print(f"\nProcessing language directory: {input_dir} -> {output_dir}")
            process_directory(input_dir, output_dir, existing_repos, force)
            processed_any = True
    return processed_any

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Convert JSON files to CSV with optional duplicate detection')
    parser.add_argument('--no-duplicate-detection', action='store_true', 
                       help='Disable duplicate detection against labeling tool')
    parser.add_argument('--force', action='store_true',
                       help='Force processing even if output files already exist')
    args = parser.parse_args()


    # Get the base directory (where the script is located)
    base_dir = Path(__file__).parent.absolute()

    # Fetch existing repository names from labeling tool for duplicate detection (if enabled)
    existing_repos = None
    if not args.no_duplicate_detection:
        existing_repos = get_existing_repos_set()

    # Primary mode: automatically process all *_json language directories
    if process_language_directories(base_dir, existing_repos=existing_repos, force=args.force):
        return  # Completed language-scoped processing

    # ---------------------------------------------------------------------
    # Fallback legacy behaviour (single default input/output locations)
    # ---------------------------------------------------------------------

    input_path = os.path.join(base_dir, DEFAULT_INPUT_DIR)
    output_path = os.path.join(base_dir, DEFAULT_OUTPUT_DIR)

    # Check if input path is a file or directory
    if os.path.isfile(input_path):
        # Process single file
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        if base_name.endswith('_pr'):
            base_name = base_name[:-3]
        output_file = os.path.join(output_path, f"{base_name}.csv")
        try:
            success = process_json_file(input_path, output_file, existing_repos, args.force)
            if success:
                print(f"Successfully converted {input_path} to {output_file}")
        except Exception as e:
            print(f"An error occurred: {e}")
    elif os.path.isdir(input_path):
        # Process directory
        process_directory(input_path, output_path, existing_repos, args.force)
    else:
        print(f"Error: Input path {input_path} does not exist")

if __name__ == '__main__':
    main()
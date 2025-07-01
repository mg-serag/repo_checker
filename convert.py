#!/usr/bin/env python3
import json
import csv
import os
import requests
import argparse
import re
from datetime import datetime
from pathlib import Path

# Default input and output paths
DEFAULT_INPUT_DIR = "json"
DEFAULT_OUTPUT_DIR = "csv"
FILTER_DATE = datetime(2024, 11, 1)

# Configuration for PR filtering
GOOD_PRS_ONLY = True  # Set to True to filter PRs based on pr_reports CSV files

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

def process_json_file(input_file, output_file, existing_repos=None, force=False, base_dir=None, language=None):
    """Process a single JSON file and convert it to CSV with comprehensive filtering and reporting."""
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

    # Initialize tracking variables for reporting
    initial_pr_count = len(data)
    after_date_filter_count = 0
    after_good_prs_filter_count = 0
    after_lt_dedup_count = 0
    after_local_dedup_count = 0
    final_pr_count = 0
    
    print(f"📊 Initial PR count: {initial_pr_count}")

    # STEP 1: Apply date filtering (mandatory)
    print(f"📅 Applying date filtering (after {FILTER_DATE.date()})")
    date_filtered_data = []
    for obj in data:
        if "pr_merged_at" in obj:
            try:
                merged_date = datetime.strptime(obj["pr_merged_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
                if merged_date >= FILTER_DATE:
                    date_filtered_data.append(obj)
            except (ValueError, TypeError):
                continue
    
    after_date_filter_count = len(date_filtered_data)
    print(f"✅ After date filtering: {after_date_filter_count} PRs")

    # STEP 2: Apply GOOD_PRS_ONLY filtering if enabled
    if GOOD_PRS_ONLY and repo_name and base_dir:
        print(f"🔍 Applying GOOD_PRS_ONLY filtering for repo: {repo_name}")
        if language:
            print(f"🌐 Language: {language}")
        
        relevant_pr_ids, good_pr_count, missing_good_prs = load_relevant_pr_ids_from_reports(repo_name, base_dir, language)
        print(f"🔍 Relevant PR IDs: {relevant_pr_ids}")
        
        if relevant_pr_ids:
            good_prs_filtered_data = []
            for obj in date_filtered_data:
                pr_id = str(obj.get("pr_id", ""))
                if pr_id in relevant_pr_ids:
                    good_prs_filtered_data.append(obj)
            after_good_prs_filter_count = len(good_prs_filtered_data)
            print(f"✅ After GOOD_PRS_ONLY filtering: {after_good_prs_filter_count} PRs")
            
            # Calculate missing Good PRs (Good PRs that are not in the JSON file)
            json_pr_ids = {str(obj.get("pr_id", "")) for obj in date_filtered_data}
            missing_good_prs_in_json = [pr_id for pr_id in missing_good_prs if pr_id not in json_pr_ids]
            missing_good_prs_count = len(missing_good_prs_in_json)
            
            if missing_good_prs_count > 0:
                print(f"⚠️ Found {missing_good_prs_count} Good PRs missing from JSON file: {missing_good_prs_in_json}")
            else:
                print(f"✅ All Good PRs found in JSON file")
        else:
            print("⚠️ No relevant PRs found, skipping all PRs")
            return {
                'repo_name': repo_name,
                'language': language,
                'initial_pr_count': initial_pr_count,
                'after_date_filter_count': after_date_filter_count,
                'after_good_prs_filter_count': 0,
                'after_lt_dedup_count': 0,
                'after_local_dedup_count': 0,
                'final_pr_count': 0,
                'good_prs_in_reports': 0,
                'missing_good_prs_count': 0,
                'success': True
            }
    else:
        # If GOOD_PRS_ONLY is not enabled, use all date-filtered PRs
        good_prs_filtered_data = date_filtered_data
        after_good_prs_filter_count = len(good_prs_filtered_data)
        good_pr_count = 0
        missing_good_prs_count = 0
        print(f"✅ Using all date-filtered PRs: {after_good_prs_filter_count} PRs")

    # STEP 3: Apply labeling tool duplicate filtering
    current_data = good_prs_filtered_data
    if existing_repos is not None and repo_name:
        lt_repo_name = convert_repo_name_to_lt_format(repo_name)
        
        if lt_repo_name in existing_repos:
            print(f"🔍 Repo {repo_name} exists in labeling tool, fetching existing PRs...")
            existing_pr_ids = get_existing_pr_ids_for_repo(repo_name)
            
            # Filter out existing PRs from labeling tool
            lt_filtered_data = [obj for obj in current_data if str(obj.get("pr_id", "")) not in existing_pr_ids]
            after_lt_dedup_count = len(lt_filtered_data)
            print(f"🔄 After LT deduplication: {after_lt_dedup_count} PRs (filtered out {len(current_data) - after_lt_dedup_count})")
            current_data = lt_filtered_data
        else:
            print(f"🔍 Repo {repo_name} not found in labeling tool, skipping LT deduplication")
            after_lt_dedup_count = len(current_data)
    else:
        after_lt_dedup_count = len(current_data)

    # STEP 4: Apply local file duplicate filtering
    if repo_name:
        output_dir = os.path.dirname(output_file)
        repo_base_name = os.path.splitext(os.path.basename(output_file))[0]
        
        # Get all existing PR IDs from local files
        local_existing_pr_ids = get_all_existing_pr_ids_for_repo(output_dir, repo_base_name)
        
        # Filter out PRs that already exist in local files
        final_data = [obj for obj in current_data if str(obj.get("pr_id", "")) not in local_existing_pr_ids]
        after_local_dedup_count = len(final_data)
        final_pr_count = after_local_dedup_count
        
        print(f"📁 Found {len(local_existing_pr_ids)} existing PRs in local files")
        print(f"🔄 After local deduplication: {final_pr_count} PRs (filtered out {len(current_data) - final_pr_count})")
    else:
        final_data = current_data
        after_local_dedup_count = len(current_data)
        final_pr_count = len(current_data)

    # STEP 5: Save the final filtered data
    # Create output directory if it doesn't exist
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Write the final filtered data to a CSV file
    with open(output_file, 'w', newline='', encoding='utf-8') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(['metadata'])
        for obj in final_data:
            json_str = json.dumps(obj)
            writer.writerow([json_str])
    
    print(f"💾 Saved {final_pr_count} PRs to {output_file}")

    # STEP 6: Create part file if there are new PRs and repo exists in LT
    if final_pr_count > 0 and existing_repos is not None and repo_name:
        lt_repo_name = convert_repo_name_to_lt_format(repo_name)
        if lt_repo_name in existing_repos:
            # Determine the next part number
            next_part_num = get_next_part_number(output_dir, repo_base_name)
            part_file = os.path.join(output_dir, f"{repo_base_name}_part_{next_part_num:02d}.csv")
            
            with open(part_file, 'w', newline='', encoding='utf-8') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(['metadata'])
                for obj in final_data:
                    json_str = json.dumps(obj)
                    writer.writerow([json_str])
            
            print(f"📄 Created new part file: {part_file} with {final_pr_count} new PRs")
        else:
            print("⏭️ Repo not in labeling tool, skipping part file creation")
    elif final_pr_count == 0:
        print("⏭️ No new PRs found, skipping part file creation")

    # Return processing statistics for reporting
    return {
        'repo_name': repo_name,
        'language': language,
        'initial_pr_count': initial_pr_count,
        'after_date_filter_count': after_date_filter_count,
        'after_good_prs_filter_count': after_good_prs_filter_count,
        'after_lt_dedup_count': after_lt_dedup_count,
        'after_local_dedup_count': after_local_dedup_count,
        'final_pr_count': final_pr_count,
        'good_prs_in_reports': good_pr_count,
        'missing_good_prs_count': missing_good_prs_count,
        'success': True
    }

def process_directory(input_dir, output_dir, existing_repos=None, force=False, base_dir=None, language=None):
    """Process all JSON files in a directory."""
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Collect statistics for reporting
    processing_stats = []

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
                result = process_json_file(input_path, output_path, existing_repos, force, base_dir, language)
                if isinstance(result, dict) and result.get('success'):
                    processing_stats.append(result)
                    print(f"✅ Successfully converted {input_path} to {output_path}")
                elif result is True:
                    # Legacy return value for backward compatibility
                    print(f"✅ Successfully processed {input_path}")
            except Exception as e:
                print(f"❌ Error processing {input_path}: {e}")
                # Add error entry to stats
                processing_stats.append({
                    'repo_name': base_name,
                    'language': language,
                    'initial_pr_count': 0,
                    'after_date_filter_count': 0,
                    'after_good_prs_filter_count': 0,
                    'after_lt_dedup_count': 0,
                    'after_local_dedup_count': 0,
                    'final_pr_count': 0,
                    'good_prs_in_reports': 0,
                    'missing_good_prs_count': 0,
                    'success': False,
                    'error': str(e)
                })
    
    return processing_stats

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
    all_processing_stats = []
    
    for entry in os.listdir(base_dir):
        if entry.endswith(json_suffix):
            input_dir = os.path.join(base_dir, entry)
            if not os.path.isdir(input_dir):
                continue  # Skip if not a directory

            # Extract language from directory name (e.g., "Java_json" -> "Java")
            language = entry.replace(json_suffix, "")
            print(f"\n{'='*60}")
            print(f"🌐 Processing language: {language}")
            print(f"{'='*60}")

            # Derive corresponding CSV directory name by swapping suffixes
            output_dir_name = entry.replace(json_suffix, csv_suffix)
            output_dir = os.path.join(base_dir, output_dir_name)

            print(f"📁 Processing language directory: {input_dir} -> {output_dir}")
            language_stats = process_directory(input_dir, output_dir, existing_repos, force, base_dir, language)
            all_processing_stats.extend(language_stats)
            processed_any = True
    
    # Create comprehensive processing report
    if all_processing_stats:
        create_processing_report(all_processing_stats, base_dir)
    
    return processed_any

def load_csv_file(file_path):
    """Load and parse a CSV file, extracting PR IDs from the metadata column."""
    if not os.path.exists(file_path):
        return set()
    
    existing_pr_ids = set()
    try:
        with open(file_path, 'r', encoding='utf-8') as csv_file:
            reader = csv.reader(csv_file)
            next(reader)  # Skip header row
            
            for row in reader:
                if row and len(row) > 0:
                    try:
                        metadata = json.loads(row[0])
                        pr_id = metadata.get("pr_id")
                        if pr_id:
                            existing_pr_ids.add(str(pr_id))
                    except (json.JSONDecodeError, KeyError):
                        continue
    except Exception as e:
        print(f"Error loading CSV file {file_path}: {e}")
    
    return existing_pr_ids

def find_all_repo_files(output_dir, repo_base_name):
    """Find all CSV files for a specific repository (including parts)."""
    repo_files = []
    
    if not os.path.exists(output_dir):
        return repo_files
    
    # Look for files that start with the repo base name
    for filename in os.listdir(output_dir):
        if filename.endswith('.csv') and filename.startswith(repo_base_name):
            file_path = os.path.join(output_dir, filename)
            repo_files.append(file_path)
    
    return sorted(repo_files)

def get_next_part_number(output_dir, repo_base_name):
    """Determine the next part number for a repository based on existing files."""
    repo_files = find_all_repo_files(output_dir, repo_base_name)
    
    if not repo_files:
        # If no files exist, start with part_02 (since part_01 would be the base file)
        return 2
    
    # Extract part numbers from existing files
    part_numbers = []
    for file_path in repo_files:
        filename = os.path.basename(file_path)
        # Check for _part_XX pattern
        match = re.search(r'_part_(\d+)\.csv$', filename)
        if match:
            part_numbers.append(int(match.group(1)))
    
    if not part_numbers:
        # If no part files exist, start with part_02
        return 2
    
    # Return the next number after the highest existing part number
    return max(part_numbers) + 1

def get_all_existing_pr_ids_for_repo(output_dir, repo_base_name):
    """Get all PR IDs from all existing files for a repository (including parts)."""
    all_pr_ids = set()
    repo_files = find_all_repo_files(output_dir, repo_base_name)
    
    for file_path in repo_files:
        file_pr_ids = load_csv_file(file_path)
        all_pr_ids.update(file_pr_ids)
    
    return all_pr_ids

def load_relevant_pr_ids_from_reports(repo_name, base_dir, language=None):
    """Load relevant PR IDs from language-specific pr_reports folder based on repo name."""
    # Convert repo name to file naming convention (USER/REPO -> USER__REPO)
    file_name = convert_repo_name_to_lt_format(repo_name) + "_relevant_prs.csv"
    
    # Determine the language-specific pr_reports directory
    if language:
        # Use language-specific folder (e.g., Java_pr_reports, JavaScript_pr_reports)
        pr_reports_dir = os.path.join(base_dir, "repo_evaluator", f"{language}_pr_reports")
    else:
        # Fallback to generic pr_reports folder
        pr_reports_dir = os.path.join(base_dir, "pr_reports")
    
    file_path = os.path.join(pr_reports_dir, file_name)
    
    if not os.path.exists(file_path):
        print(f"Warning: Relevant PRs file not found: {file_path}")
        return set(), 0, 0  # Return empty set and zero counts
    
    relevant_pr_ids = set()
    good_pr_count = 0
    unchecked_pr_count = 0
    missing_good_prs = []  # Track Good PRs that might be missing from JSON
    
    try:
        with open(file_path, 'r', encoding='utf-8') as csv_file:
            reader = csv.reader(csv_file)
            header = next(reader)  # Get header row
            
            # Find the index of the agent_result column
            agent_result_index = None
            for i, col in enumerate(header):
                if col.strip().lower() == 'agent_result':
                    agent_result_index = i
                    break
            
            if agent_result_index is None:
                print(f"Warning: agent_result column not found in {file_path}, including all PRs")
                # Fallback: include all PRs if agent_result column is not found
                for row in reader:
                    if row and len(row) > 0:
                        pr_id = row[0].strip()  # First column contains PR number/ID
                        if pr_id and pr_id.isdigit():
                            relevant_pr_ids.add(pr_id)
            else:
                # Filter based on agent_result column
                for row in reader:
                    if row and len(row) > agent_result_index:
                        pr_id = row[0].strip()  # First column contains PR number/ID
                        agent_result = row[agent_result_index].strip() if len(row) > agent_result_index else ""
                        
                        if pr_id and pr_id.isdigit():
                            # Include PRs with "Good PR" or "Not Checked" status
                            if agent_result == "Good PR":
                                relevant_pr_ids.add(pr_id)
                                good_pr_count += 1
                                missing_good_prs.append(pr_id)  # Track for potential missing analysis
                            elif agent_result == "Not Checked":
                                relevant_pr_ids.add(pr_id)
                                unchecked_pr_count += 1
                            # Note: "Bad PR" PRs are excluded
                            
    except Exception as e:
        print(f"Error loading relevant PRs file {file_path}: {e}")
    
    print(f"Loaded {len(relevant_pr_ids)} relevant PR IDs from {file_path}")
    print(f"  - Good PRs: {good_pr_count}")
    print(f"  - Not Checked PRs: {unchecked_pr_count}")
    print(f"  - Good PRs tracked for missing analysis: {len(missing_good_prs)}")
    
    return relevant_pr_ids, good_pr_count, missing_good_prs

def create_processing_report(processing_stats, base_dir):
    """Create a comprehensive CSV report of processing statistics."""
    if not processing_stats:
        return
    
    # Generate ISO timestamp for filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"processing_report_{timestamp}.csv"
    report_path = os.path.join(base_dir, report_filename)
    
    # Calculate summary statistics
    total_repos = len(processing_stats)
    successful_repos = sum(1 for stat in processing_stats if stat.get('success', False))
    failed_repos = total_repos - successful_repos
    
    total_initial_prs = sum(stat.get('initial_pr_count', 0) for stat in processing_stats)
    total_after_date = sum(stat.get('after_date_filter_count', 0) for stat in processing_stats)
    total_after_good_prs = sum(stat.get('after_good_prs_filter_count', 0) for stat in processing_stats)
    total_after_lt_dedup = sum(stat.get('after_lt_dedup_count', 0) for stat in processing_stats)
    total_after_local_dedup = sum(stat.get('after_local_dedup_count', 0) for stat in processing_stats)
    total_final_prs = sum(stat.get('final_pr_count', 0) for stat in processing_stats)
    total_good_prs_in_reports = sum(stat.get('good_prs_in_reports', 0) for stat in processing_stats)
    total_missing_good_prs = sum(stat.get('missing_good_prs_count', 0) for stat in processing_stats)
    
    # Write the report
    with open(report_path, 'w', newline='', encoding='utf-8') as csv_file:
        writer = csv.writer(csv_file)
        
        # Write summary header
        writer.writerow(['PROCESSING SUMMARY REPORT'])
        writer.writerow([f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'])
        writer.writerow([f'Total Repositories Processed: {total_repos}'])
        writer.writerow([f'Successful: {successful_repos}'])
        writer.writerow([f'Failed: {failed_repos}'])
        writer.writerow([])
        
        # Write totals
        writer.writerow(['TOTALS ACROSS ALL REPOSITORIES'])
        writer.writerow(['Initial PRs', 'After Date Filter', 'After Good PRs Filter', 'After LT Dedup', 'After Local Dedup', 'Final PRs'])
        writer.writerow([total_initial_prs, total_after_date, total_after_good_prs, total_after_lt_dedup, total_after_local_dedup, total_final_prs])
        writer.writerow([])
        
        # Write Good PRs analysis
        writer.writerow(['GOOD PRS ANALYSIS'])
        writer.writerow(['Good PRs in Reports', 'Missing Good PRs', 'Recovery Rate'])
        recovery_rate = ((total_good_prs_in_reports - total_missing_good_prs) / total_good_prs_in_reports * 100) if total_good_prs_in_reports > 0 else 0
        writer.writerow([total_good_prs_in_reports, total_missing_good_prs, f"{recovery_rate:.1f}%"])
        writer.writerow([])
        
        # Write detailed repository data
        writer.writerow(['DETAILED REPOSITORY STATISTICS'])
        writer.writerow(['Repository', 'Language', 'Initial PRs', 'After Date Filter', 'After Good PRs Filter', 'After LT Dedup', 'After Local Dedup', 'Final PRs', 'Good PRs in Reports', 'Missing Good PRs Count', 'Status', 'Error'])
        
        for stat in processing_stats:
            writer.writerow([
                stat.get('repo_name', 'Unknown'),
                stat.get('language', 'Unknown'),
                stat.get('initial_pr_count', 0),
                stat.get('after_date_filter_count', 0),
                stat.get('after_good_prs_filter_count', 0),
                stat.get('after_lt_dedup_count', 0),
                stat.get('after_local_dedup_count', 0),
                stat.get('final_pr_count', 0),
                stat.get('good_prs_in_reports', 0),
                stat.get('missing_good_prs_count', 0),
                'Success' if stat.get('success', False) else 'Failed',
                stat.get('error', '')
            ])
    
    print(f"\n📊 Processing report saved to: {report_path}")
    print(f"📈 Summary: {successful_repos}/{total_repos} repositories processed successfully")
    print(f"📊 Total PRs: {total_initial_prs} → {total_final_prs} (final)")
    print(f"📊 Good PRs Analysis: {total_good_prs_in_reports} Good PRs in reports, {total_missing_good_prs} missing from JSON files")
    if total_good_prs_in_reports > 0:
        recovery_rate = ((total_good_prs_in_reports - total_missing_good_prs) / total_good_prs_in_reports * 100)
        print(f"📊 Good PRs Recovery Rate: {recovery_rate:.1f}%")
    
    return report_path

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Convert JSON files to CSV with optional duplicate detection')
    parser.add_argument('--no-duplicate-detection', action='store_true', 
                       help='Disable duplicate detection against labeling tool')
    parser.add_argument('--force', action='store_true',
                       help='Force processing even if output files already exist')
    parser.add_argument('--good-prs-only', action='store_true',
                       help='Filter PRs based on relevant PRs from pr_reports folder instead of date')
    args = parser.parse_args()

    # Update global configuration based on command line arguments
    global GOOD_PRS_ONLY
    if args.good_prs_only:
        GOOD_PRS_ONLY = True
        print("GOOD_PRS_ONLY mode enabled - filtering based on relevant PRs from pr_reports folder")

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

    # Collect statistics for legacy processing
    legacy_stats = []

    # Check if input path is a file or directory
    if os.path.isfile(input_path):
        # Process single file
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        if base_name.endswith('_pr'):
            base_name = base_name[:-3]
        output_file = os.path.join(output_path, f"{base_name}.csv")
        try:
            result = process_json_file(input_path, output_file, existing_repos, args.force, base_dir, None)
            if isinstance(result, dict) and result.get('success'):
                legacy_stats.append(result)
                print(f"✅ Successfully converted {input_path} to {output_file}")
            elif result is True:
                print(f"✅ Successfully processed {input_path}")
        except Exception as e:
            print(f"❌ An error occurred: {e}")
            legacy_stats.append({
                'repo_name': base_name,
                'language': 'Unknown',
                'initial_pr_count': 0,
                'after_date_filter_count': 0,
                'after_good_prs_filter_count': 0,
                'after_lt_dedup_count': 0,
                'after_local_dedup_count': 0,
                'final_pr_count': 0,
                'good_prs_in_reports': 0,
                'missing_good_prs_count': 0,
                'success': False,
                'error': str(e)
            })
    elif os.path.isdir(input_path):
        # Process directory
        legacy_stats = process_directory(input_path, output_path, existing_repos, args.force, base_dir, None)
    else:
        print(f"❌ Error: Input path {input_path} does not exist")
        return

    # Create report for legacy processing if any files were processed
    if legacy_stats:
        create_processing_report(legacy_stats, base_dir)

if __name__ == '__main__':
    main()
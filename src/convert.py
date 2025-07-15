#!/usr/bin/env python3
import json
import csv
import os
import requests
import argparse
import re
from datetime import datetime
import glob

# Import centralized configuration functions
from config_utils import get_all_language_configs, get_lt_token

# Default input and output paths
DEFAULT_INPUT_DIR = "json"
DEFAULT_OUTPUT_DIR = "csv"
FILTER_DATE = datetime(2024, 11, 1)

# Configuration for PR filtering
GOOD_PRS_ONLY = True  # Set to True to filter PRs based on pr_reports CSV files

LANGUAGE_JSON_SUFFIX = "_json"
LANGUAGE_CSV_SUFFIX = "_csv"

# LT API Configuration
LT_TOKEN = get_lt_token()
BASE_BATCHES_URL = "https://eval.turing.com/api/batches?sort%5B0%5D=createdAt%2CDESC&join%5B0%5D=batchStats&join%5B1%5D=importAttempts"
BASE_CONVERSATIONS_URL = "https://eval.turing.com/api/conversations?join%5B0%5D=project%7C%7Cid%2Cname&join%5B1%5D=batch%7C%7Cid%2Cname&join%5B2%5D=seed%7C%7Cmetadata"

def get_all_project_ids():
    """Get all project IDs from language configuration."""
    try:
        all_languages = get_all_language_configs()
        project_ids = set()
        
        for lang_config in all_languages.values():
            project_id = lang_config.get('project_id')
            if project_id:
                project_ids.add(project_id)
        
        return sorted(project_ids)
    except (FileNotFoundError, KeyError):
        # Fallback to known project IDs including Python=40
        return [40, 41, 42, 43, 44, 45, 46, 47]

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
    """Fetches all existing repository names from the labeling tool for all configured projects."""
    print("Fetching existing repository names from labeling tool for all configured projects...")
    existing_repos = set()
    
    # Get all project IDs from configuration
    project_ids = get_all_project_ids()
    print(f"Checking projects: {project_ids}")
    
    # Get all repositories from all configured projects
    for project_id in project_ids:
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
    
    print(f"\nFound {len(existing_repos)} total repositories across all configured projects")
    return existing_repos

def check_repo_exists_in_lt(repo_name):
    """Check if a repository exists in the labeling tool across all configured projects."""
    print(f"Checking if repo {repo_name} exists in labeling tool across all configured projects...")
    
    # Convert repo name to LT format (USER/REPO -> USER__REPO)
    lt_repo_name = convert_repo_name_to_lt_format(repo_name)
    
    # Get all project IDs from configuration
    project_ids = get_all_project_ids()
    
    # Check all configured projects
    for project_id in project_ids:
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
    
    print(f"Repo {repo_name} not found in any configured project in labeling tool")
    return False

def convert_repo_name_to_lt_format(repo_name):
    """Convert USER/REPO format to USER__REPO format for LT comparison."""
    return repo_name.replace("/", "__")

def clean_metadata(obj):
    """Keep only essential metadata fields and remove everything else."""
    essential_fields = [
        'repo',
        'pr_id', 
        'swe_url',
        'issue_id',
        'repo_url',
        'base_commit',
        'head_commit',
        'instance_id',
        'pr_merged_at',
        'issue_word_count',
        'test_files_count',
        'problem_statement'
    ]
    
    # Create a new object with only the essential fields
    cleaned_obj = {}
    for field in essential_fields:
        if field in obj:
            cleaned_obj[field] = obj[field]
    
    return cleaned_obj

def validate_pr_data(obj):
    """Validate that a PR object has the minimum required fields.
    
    Args:
        obj: PR object to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    required_fields = ['pr_id', 'swe_url', 'issue_id']
    
    for field in required_fields:
        if field not in obj or not obj[field]:
            return False
    
    return True

def get_existing_pr_ids_for_repo(repo_name):
    """Fetches existing PR IDs for a specific repository from the labeling tool."""
    print(f"Fetching existing PR IDs for repo: {repo_name}")
    
    # Convert repo name to LT format (USER/REPO -> USER__REPO)
    lt_repo_name = convert_repo_name_to_lt_format(repo_name)
    existing_pr_ids = set()
    
    # Get all project IDs from configuration
    project_ids = get_all_project_ids()
    
    # Check all configured projects
    for project_id in project_ids:
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

def process_json_file(input_file, output_file, existing_repos=None, force=False, base_dir=None, language=None, upload_mode='Good'):
    """
    Process a single JSON file, filter PRs, and convert to CSV.
    Now returns detailed processing statistics.
    """
    stats = {
        'initial_pr_count': 0,
        'after_date_filter_count': 0,
        'logical_pr_count': 0,
        'good_pr_count': 0,
        'final_pr_count': 0,
        'uploaded_pr_count': 0,
        'missing_pr_ids': []
    }

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error reading JSON file {input_file}: {e}")
        return {**stats, 'success': False}
    
    stats['initial_pr_count'] = len(data)
    
    # 1. Date Filtering
    # Keep PRs merged on or after the cutoff date (FILTER_DATE). The previous
    # implementation used a '<' comparison which unintentionally excluded
    # these newer PRs and resulted in empty results even when relevant PRs
    # existed. We now use ">=" to include PRs that meet or exceed the
    # threshold.
    date_filtered_data = [
        obj for obj in data
        if 'pr_merged_at' in obj and obj['pr_merged_at'] and
        datetime.fromisoformat(obj['pr_merged_at'].replace('Z', '')) >= FILTER_DATE
    ]
    stats['after_date_filter_count'] = len(date_filtered_data)

    repo_name = data[0].get('repo') if data else None
    
    # 2. Upload Mode Filtering (Logical or Good)
    if upload_mode in ['Logical', 'Good']:
        relevant_pr_ids, good_pr_ids = load_relevant_pr_ids_from_reports(repo_name, base_dir, language, upload_mode)
        
        if upload_mode == 'Logical':
            filtered_data = [pr for pr in date_filtered_data if str(pr.get('pr_id')) in relevant_pr_ids]
            stats['logical_pr_count'] = len(filtered_data)
        else: # 'Good'
            filtered_data = [pr for pr in date_filtered_data if str(pr.get('pr_id')) in good_pr_ids]
            stats['good_pr_count'] = len(filtered_data)
            # We can also report the total logical PRs found in reports for context
            stats['logical_pr_count'] = len(relevant_pr_ids)

    else: # 'All'
        filtered_data = date_filtered_data
        stats['logical_pr_count'] = len(filtered_data) # In 'All' mode, all are considered 'logical'
        stats['good_pr_count'] = len(filtered_data) # and 'good' for stat purposes

    # This is the final count of PRs after all filtering, before writing to CSV
    stats['final_pr_count'] = len(filtered_data)
    
    # Write to CSV
    if filtered_data:
        # Clean metadata and write to CSV
        final_rows = [clean_metadata(pr) for pr in filtered_data]

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['metadata'])
            for row in final_rows:
                writer.writerow([json.dumps(row)])

        stats['uploaded_pr_count'] = len(final_rows)
    else:
        stats['uploaded_pr_count'] = 0

    # Calculate missing PR IDs
    initial_ids = {str(pr.get('pr_id')) for pr in data}
    final_ids = {str(pr.get('pr_id')) for pr in filtered_data}
    missing_ids = sorted(list(initial_ids - final_ids))
    stats['missing_pr_ids'] = missing_ids
    
    return {**stats, 'success': True}

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
                    'after_validation_count': 0,
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

def load_relevant_pr_ids_from_reports(repo_name, base_dir, language=None, upload_mode='Good'):
    """Load relevant PR IDs from language-specific pr_reports folder based on repo name.
    
    Args:
        repo_name: Name of the repository
        base_dir: Base directory for finding PR reports
        language: Target language for processing
        upload_mode: Upload filtering mode ('Good', 'Logical')
            - Good: Only include PRs marked as "Good PR"
            - Logical: Include all PRs in the report (good or bad)
    """
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
        print(f"⚠️ No relevant PRs file found: {file_path}")
        print(f"   Including all PRs for {repo_name} (no filtering applied)")
        return set(), set()  # Return empty sets to include all PRs
    
    relevant_pr_ids = set()
    good_pr_ids = set() # New set to store only Good PR IDs
    
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
                print(f"⚠️ agent_result column not found in {file_path}, including all PRs")
                # Fallback: include all PRs if agent_result column is not found
                for row in reader:
                    if row and len(row) > 0:
                        pr_id = row[0].strip()  # First column contains PR number/ID
                        if pr_id and pr_id.isdigit():
                            relevant_pr_ids.add(pr_id)
            else:
                # Filter based on agent_result column and upload mode
                for row in reader:
                    if row and len(row) > agent_result_index:
                        pr_id = row[0].strip()  # First column contains PR number/ID
                        agent_result = row[agent_result_index].strip() if len(row) > agent_result_index else ""
                        
                        if pr_id and pr_id.isdigit():
                            if upload_mode == 'Good':
                                # Good mode: Only include PRs with "Good PR" status
                                if agent_result == "Good PR":
                                    relevant_pr_ids.add(pr_id)
                                    good_pr_ids.add(pr_id) # Add to good_pr_ids
                                elif agent_result == "Not Checked":
                                    relevant_pr_ids.add(pr_id)
                                # Note: "Bad PR" PRs are excluded
                            else:  # Logical mode
                                # Logical mode: Include all PRs in the report (good, bad, or unchecked)
                                if agent_result in ["Good PR", "Bad PR", "Not Checked"]:
                                    relevant_pr_ids.add(pr_id)
                                    if agent_result == "Good PR":
                                        good_pr_ids.add(pr_id) # Add to good_pr_ids
                                    elif agent_result == "Not Checked":
                                        pass # No need to add to good_pr_ids
                            
    except Exception as e:
        print(f"❌ Error loading relevant PRs file {file_path}: {e}")
        print(f"   Including all PRs for {repo_name} (error in file reading)")
        return set(), set()  # Return empty sets to include all PRs
    
    print(f"Loaded {len(relevant_pr_ids)} relevant PR IDs from {file_path}")
    print(f"  - Good PRs: {len(good_pr_ids)}")
    print(f"  - Total PRs in report: {len(relevant_pr_ids)}")
    
    return relevant_pr_ids, good_pr_ids

def create_processing_report(processing_stats, base_dir):
    """Create a comprehensive CSV report of processing statistics."""
    if not processing_stats:
        return
    
    # Create processing_reports directory if it doesn't exist
    # Use relative path from base_dir to processing_reports
    reports_dir = os.path.join(base_dir, "processing_reports")
    os.makedirs(reports_dir, exist_ok=True)
    
    # Generate ISO timestamp for filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"processing_report_{timestamp}.csv"
    report_path = os.path.join(reports_dir, report_filename)
    
    # Calculate summary statistics
    total_repos = len(processing_stats)
    successful_repos = sum(1 for stat in processing_stats if stat.get('success', False))
    failed_repos = total_repos - successful_repos
    
    total_initial_prs = sum(stat.get('initial_pr_count', 0) for stat in processing_stats)
    total_after_validation = sum(stat.get('after_date_filter_count', 0) for stat in processing_stats)
    total_after_date = sum(stat.get('after_date_filter_count', 0) for stat in processing_stats)
    total_after_good_prs = sum(stat.get('good_pr_count', 0) for stat in processing_stats)
    total_after_lt_dedup = sum(stat.get('after_lt_dedup_count', 0) for stat in processing_stats)
    total_after_local_dedup = sum(stat.get('after_local_dedup_count', 0) for stat in processing_stats)
    total_final_prs = sum(stat.get('final_pr_count', 0) for stat in processing_stats)
    total_good_prs_in_reports = sum(stat.get('good_pr_count', 0) for stat in processing_stats)
    total_missing_good_prs = sum(stat.get('missing_good_prs_count', 0) for stat in processing_stats)
    
    # Count repositories with no usable PRs
    repos_with_no_prs = sum(1 for stat in processing_stats if stat.get('final_pr_count', 0) == 0)
    
    # Write the report
    with open(report_path, 'w', newline='', encoding='utf-8') as csv_file:
        writer = csv.writer(csv_file)
        
        # Write summary header
        writer.writerow(['PROCESSING SUMMARY REPORT'])
        writer.writerow([f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'])
        writer.writerow([f'Total Repositories Processed: {total_repos}'])
        writer.writerow([f'Successful: {successful_repos}'])
        writer.writerow([f'Failed: {failed_repos}'])
        writer.writerow([f'Repositories with No Usable PRs: {repos_with_no_prs}'])
        writer.writerow([])
        
        # Write totals
        writer.writerow(['TOTALS ACROSS ALL REPOSITORIES'])
        writer.writerow(['Initial PRs', 'After Validation', 'After Date Filter', 'After Good PRs Filter', 'After LT Dedup', 'After Local Dedup', 'Final PRs'])
        writer.writerow([total_initial_prs, total_after_validation, total_after_date, total_after_good_prs, total_after_lt_dedup, total_after_local_dedup, total_final_prs])
        writer.writerow([])
        
        # Write Good PRs analysis
        writer.writerow(['GOOD PRS ANALYSIS'])
        writer.writerow(['Good PRs in Reports', 'Missing Good PRs', 'Recovery Rate'])
        recovery_rate = ((total_good_prs_in_reports - total_missing_good_prs) / total_good_prs_in_reports * 100) if total_good_prs_in_reports > 0 else 0
        writer.writerow([total_good_prs_in_reports, total_missing_good_prs, f"{recovery_rate:.1f}%"])
        writer.writerow([])
        
        # Write detailed repository data
        writer.writerow(['DETAILED REPOSITORY STATISTICS'])
        writer.writerow(['Repository', 'Language', 'Upload Mode', 'Initial PRs', 'After Validation', 'After Date Filter', 'After Good PRs Filter', 'After LT Dedup', 'After Local Dedup', 'Final PRs', 'Good PRs in Reports', 'Missing Good PRs Count', 'Status', 'Error', 'No Usable PRs Reason'])
        
        for stat in processing_stats:
            # Determine reason for no usable PRs
            no_prs_reason = ""
            if stat.get('final_pr_count', 0) == 0:
                if stat.get('after_date_filter_count', 0) == 0:
                    no_prs_reason = "All PRs filtered out by date"
                elif stat.get('good_pr_count', 0) == 0:
                    no_prs_reason = "All PRs filtered out by upload mode filtering"
                elif stat.get('after_lt_dedup_count', 0) == 0:
                    no_prs_reason = "All PRs already in labeling tool"
                elif stat.get('after_local_dedup_count', 0) == 0:
                    no_prs_reason = "All PRs already in local files"
                else:
                    no_prs_reason = "Unknown filtering issue"
            
            writer.writerow([
                stat.get('repo_name', 'Unknown'),
                stat.get('language', 'Unknown'),
                stat.get('upload_mode', 'Unknown'),
                stat.get('initial_pr_count', 0),
                stat.get('after_date_filter_count', 0),
                stat.get('good_pr_count', 0), # Changed from after_good_prs_filter_count
                stat.get('after_lt_dedup_count', 0),
                stat.get('after_local_dedup_count', 0),
                stat.get('final_pr_count', 0),
                stat.get('good_pr_count', 0), # Changed from good_prs_in_reports
                stat.get('missing_good_prs_count', 0),
                'Success' if stat.get('success', False) else 'Failed',
                stat.get('error', ''),
                no_prs_reason
            ])
    
    print(f"\n📊 Processing report saved to: {report_path}")
    print(f"📈 Summary: {successful_repos}/{total_repos} repositories processed successfully")
    print(f"📊 Total PRs: {total_initial_prs} → {total_after_validation} (valid) → {total_final_prs} (final)")
    print(f"📊 Good PRs Analysis: {total_good_prs_in_reports} Good PRs in reports, {total_missing_good_prs} missing from JSON files")
    if total_good_prs_in_reports > 0:
        recovery_rate = ((total_good_prs_in_reports - total_missing_good_prs) / total_good_prs_in_reports * 100)
        print(f"📊 Good PRs Recovery Rate: {recovery_rate:.1f}%")
    print(f"⚠️ Repositories with no usable PRs: {repos_with_no_prs}")
    
    return report_path

def convert_folder(source_directory, output_directory):
    """
    Converts all JSON files in a source directory to CSV files in an output directory.
    """
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
        print(f"Created output directory: {output_directory}")

    json_files = glob.glob(os.path.join(source_directory, '*.json'))
    print(f"Found {len(json_files)} JSON files in {source_directory}")

    for json_file in json_files:
        try:
            base_name = os.path.basename(json_file).replace('.json', '')
            csv_file = os.path.join(output_directory, f"{base_name}.csv")
            print(f"Processing {json_file} -> {csv_file}")
            process_json_file(json_file, csv_file)
        except Exception as e:
            print(f"Error processing {json_file}: {e}")

def main():
    """
    Main function to run the conversion as a standalone script.
    """
    parser = argparse.ArgumentParser(description="Convert JSON files from SWE-bench to CSV format.")
    parser.add_argument("source_directory", help="The directory containing the JSON files to process.")
    parser.add_argument("output_directory", help="The directory where CSV files will be saved.")
    args = parser.parse_args()

    print(f"Starting conversion from '{args.source_directory}' to '{args.output_directory}'")
    convert_folder(args.source_directory, args.output_directory)
    print("Conversion complete.")

if __name__ == "__main__":
    # To run this script:
    # python convert.py path/to/json_folder path/to/csv_folder
    main()
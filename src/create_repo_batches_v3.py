#!/usr/bin/env python3
"""
SWE-Bench Batch Creator V3
---------------------------
Clean, modular implementation for processing repositories and creating SWE-Bench batches.
Leverages utility classes for configuration and sheet management.
Features async job management for significantly improved performance and quality filtering.

Key Features:
- Async job management: Start all SWE-Bench jobs concurrently (max 10 at a time) for faster processing
- Smart deduplication with part files
- Configurable re-triggering of jobs
- Resource-aware concurrent processing
- Minimum PR threshold (default: 2) for batch uploads
- Comprehensive reporting and statistics

Usage Options:
1. Direct execution (modify DEFAULT_* constants at top of script):
   python create_repo_batches_v3.py

2. Command line with language:
   python create_repo_batches_v3.py JavaScript

3. With manual repos:
   python create_repo_batches_v3.py JavaScript --manual user/repo1 user/repo2

4. With custom count:
   python create_repo_batches_v3.py JavaScript --count 20

5. With upload mode:
   python create_repo_batches_v3.py JavaScript --upload-mode Good

6. Use existing jobs (no re-trigger):
   python create_repo_batches_v3.py JavaScript --no-retrigger

Performance: V3 processes multiple repositories concurrently (max 10 parallel jobs), reducing total 
processing time from O(n*job_time) to O(ceil(n/10)*job_time) when processing n repositories.
"""

import json
import os
import sys
import time
import argparse
import requests
import re
import csv
import threading
import concurrent.futures
from datetime import datetime
from urllib.parse import urlparse
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any, Tuple
import pandas as pd
from bs4 import BeautifulSoup
from diskcache import FanoutCache

# Import utility modules
from config_utils import (
    get_lt_token, get_swe_token, get_language_config, get_language_project_id,
    get_language_json_folder, get_language_csv_folder, get_language_sheet_name
)
from sheet_utils import (
    get_google_sheet, _get_gspread_client, get_column_indices, 
    fetch_sheet_data, update_sheet_cells, get_spreadsheet_key
)
from convert import process_json_file

# ---------------------------------------------------------------------------
# DIRECT EXECUTION CONFIGURATION
# ---------------------------------------------------------------------------
# Modify these values to run the script directly without command line arguments

# Language settings (change as needed)
LANGUAGE = "C/C++"

# Count for repositories to process
TARGET_COUNT = 10

# Upload filtering mode - controls which PRs to include in the final CSV
# All: Upload all PRs found in the JSON file (only do deduplication step)
# Good: Filter to include only Good PRs (PRs marked as "Good PR" in the PR reports)
# Logical: Filter to include all PRs in the PR report whether the agent judged them as good or bad
UPLOAD_MODE = 'Logical'  # Options: 'All', 'Good', 'Logical'

# Use manual repos or spreadsheet
USE_MANUAL_REPOS = True  # Set to False to use spreadsheet

# Re-trigger SWE-Bench jobs to get fresh data (recommended after system updates)
RETRIGGER_JOBS = True  # Set to False to use existing completed jobs

# Concurrent job limits to manage resource usage
MAX_CONCURRENT_JOBS = 10  # Maximum number of jobs to run in parallel

# Minimum PR threshold for batch uploads
MIN_PRS_FOR_UPLOAD = 2  # Minimum number of usable PRs required to upload a batch

# Manual repository list (only used if USE_MANUAL_REPOS = True)
MANUAL_REPOS = [
    "apache/arrow", "DynamoRIO/dynamorio", "pocoproject/poco", "fluent/fluent-bit", "valkey-io/valkey"
    # "wevm/viem",
    # "apache/seatunnel",
    # "checkstyle/checkstyle"
    # "elastic/kibana",
    # "prebid/Prebid.js",
    # "danny-avila/LibreChat",
]

# ---------------------------------------------------------------------------
# QUICK START: To run with defaults, simply execute:
#   python create_repo_batches_v3.py
# 
# This will use the configuration values above. Modify them as needed.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Configuration and Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ProcessingConfig:
    """Configuration for batch processing."""
    language: str
    target_count: int = 30
    upload_mode: str = 'Logical'  # 'All', 'Good', 'Logical'
    use_manual_repos: bool = False
    manual_repos: List[str] = field(default_factory=list)
    retrigger_jobs: bool = True  # Re-trigger SWE-Bench jobs for fresh data
    
    def __post_init__(self):
        # Load language-specific configuration
        self.lang_config = get_language_config(self.language)
        self.project_id = get_language_project_id(self.language)
        self.json_folder = get_language_json_folder(self.language)
        self.csv_folder = get_language_csv_folder(self.language)
        self.sheet_name = get_language_sheet_name(self.language)
        
        # Ensure directories exist
        os.makedirs(self.json_folder, exist_ok=True)
        os.makedirs(self.csv_folder, exist_ok=True)

@dataclass
class RepositoryStats:
    """Statistics for a single repository."""
    repository: str
    status: str = 'pending'
    initial_pr_count: int = 0
    after_date_filter_count: int = 0
    logical_pr_count: int = 0
    good_pr_count: int = 0
    final_pr_count: int = 0
    uploaded_pr_count: int = 0
    missing_pr_ids: List[str] = field(default_factory=list)
    error_message: str = ''
    success: bool = False

@dataclass
class JobInfo:
    """Information about a SWE-Bench job."""
    repo_name: str
    job_id: Optional[str] = None
    status: str = 'pending'  # pending, in_progress, completed, failed
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error_message: str = ''

@dataclass
class ProcessingSummary:
    """Summary of batch processing results."""
    total_repos: int = 0
    successful_repos: int = 0
    failed_repos: int = 0
    skipped_repos: int = 0
    no_prs_repos: int = 0
    total_prs_processed: int = 0
    total_prs_uploaded: int = 0
    repository_stats: List[RepositoryStats] = field(default_factory=list)

# ---------------------------------------------------------------------------
# SWE-Bench Client
# ---------------------------------------------------------------------------

class SWEBenchClient:
    """Handles all SWE-Bench API interactions."""
    
    def __init__(self, config: ProcessingConfig):
        self.config = config
        self.swe_token = get_swe_token()
        self.lt_token = get_lt_token()
        self.cache = FanoutCache("cache")
        
        self.auth_cookies = {
            "auth_token": self.swe_token,
            "eval_access_token": self.lt_token,
        }
        self.default_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    
    def _make_api_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """Centralized API request handler with error handling."""
        headers = kwargs.setdefault("headers", {})
        headers.update(self.default_headers)
        
        for attempt in range(3):
            try:
                res = requests.request(method, url, **kwargs)
                
                if res.status_code == 401:
                    hostname = urlparse(url).hostname
                    token_name = "LT_TOKEN" if "eval.turing.com" in hostname else "SWE_TOKEN"
                    print(f"❌ FATAL: 401 Unauthorized - {token_name} expired/invalid")
                    sys.exit(1)
                    
                res.raise_for_status()
                return res
                
            except requests.exceptions.RequestException as e:
                if attempt < 2:
                    print(f"⚠️ Network error for {url}: {e}. Retrying in 5s...")
                    time.sleep(5)
                else:
                    print(f"❌ Failed to make request to {url} after 3 attempts: {e}")
                    return None
        return None
    
    def get_or_start_job(self, repo_name: str) -> Optional[str]:
        """Get existing job ID or start a new job for a repository."""
        repo_safe = repo_name.replace("/", "__")
        
        if self.config.retrigger_jobs:
            print(f"🔄 Re-triggering job for {repo_name} to get fresh data")
            return self._start_job(repo_safe)
        else:
            # Check for existing job
            job_id = self._get_job_id(repo_safe)
            if job_id:
                print(f"♻️ Using existing job {job_id} for {repo_name}")
                return job_id
            
            # Start new job if none exists
            return self._start_job(repo_safe)
    
    def _get_job_id(self, repo_safe: str) -> Optional[str]:
        """Get existing job ID for a repository."""
        url = f"https://swe-bench-plus.turing.com/api/jobs/get?topic=get_relevant_prs&repo_id={repo_safe}"
        res = self._make_api_request("get", url, cookies=self.auth_cookies)
        
        if not res:
            return None
        
        try:
            info = res.json()
            if info.get("status") in {"COMPLETED", "IN_PROGRESS", "NEW"}:
                return info.get("id")
        except json.JSONDecodeError:
            pass
        
        return None
    
    def _start_job(self, repo_safe: str) -> Optional[str]:
        """Start a new job for a repository."""
        url = "https://swe-bench-plus.turing.com/api/jobs"
        payload = {
            "topic": "get_relevant_prs",
            "payload": {
                "repo_id": repo_safe,
                "run_with_dockerfile": True,
                "repo": {
                    "repo": repo_safe,
                    "repo_id": repo_safe,
                    "language": self.config.language,
                    "dockerfile": None,
                    "updated_by_user_email": None,
                },
                "repo_name": repo_safe,
                "min_test_files": 1,
                "max_non_test_files": 100,
                "max_prs": 1000,
            },
        }
        
        res = self._make_api_request("post", url, json=payload, cookies=self.auth_cookies)
        if not res or "application/json" not in res.headers.get("Content-Type", ""):
            print(f"❌ Failed to start job for {repo_safe}")
            return None
        
        return res.json().get("jobId")
    
    def wait_for_job_completion(self, job_id: str, repo_name: str) -> bool:
        """Wait for job completion and return success status."""
        while True:
            status = self._get_job_status(job_id)
            print(f"⏳ {repo_name} – job {job_id} status: {status}")
            
            if status == "COMPLETED":
                time.sleep(3)  # Allow time for webpage data to load
                return True
            elif status in {"FAILED", "CANCELLED"}:
                print(f"❌ Job failed for {repo_name}: {status}")
                return False
            
            time.sleep(10)
    
    def _get_job_status(self, job_id: str) -> str:
        """Get job status."""
        url = f"https://swe-bench-plus.turing.com/api/jobs/{job_id}"
        res = self._make_api_request("get", url, cookies=self.auth_cookies)
        
        if not res:
            return "FAILED"
        
        return res.json().get("status", "UNKNOWN")
    
    def get_pr_data_from_webpage(self, repo_name: str, max_retries: int = 3) -> List[Dict]:
        """Scrape PR data from SWE-Bench webpage."""
        repo_safe = repo_name.replace("/", "__")
        print(f"🌐 Scraping webpage for {repo_name} PR data...")
        
        for attempt in range(max_retries):
            try:
                # Clear cache for fresh data
                self.cache.delete(f'{repo_safe}_response')
                
                url = f'https://swe-bench-plus.turing.com/repos/{repo_safe}'
                print(f"🔍 Attempt {attempt + 1}/{max_retries}: Fetching {url}")
                
                response = self._make_api_request(
                    "get", url, 
                    cookies=self.auth_cookies, 
                    headers={"Accept": "text/html"}
                )
                
                if not response:
                    if attempt < max_retries - 1:
                        print(f"⏳ Retrying in 10 seconds...")
                        time.sleep(10)
                        continue
                    return []
                
                # Cache response
                self.cache.set(f'{repo_safe}_response', response.text)
                
                # Parse HTML
                soup = BeautifulSoup(response.text, "html.parser")
                script = soup.find("script", id="__NEXT_DATA__")
                
                if not script:
                    if attempt < max_retries - 1:
                        print(f"⏳ Retrying in 10 seconds...")
                        time.sleep(10)
                        continue
                    return []
                
                # Extract PR data
                data = json.loads(script.text)
                rows = (data.get('props', {})
                           .get('pageProps', {})
                           .get('rows', []))
                
                if rows:
                    print(f"✅ Found {len(rows)} rows")
                    return rows
                
                if attempt < max_retries - 1:
                    print(f"⏳ Retrying in 10 seconds... (data might still be loading)")
                    time.sleep(10)
                    
            except (json.JSONDecodeError, Exception) as e:
                print(f"❌ Error parsing data for {repo_name}: {e}")
                if attempt < max_retries - 1:
                    print(f"⏳ Retrying in 10 seconds...")
                    time.sleep(10)
        
        return []
    
    def start_multiple_jobs(self, repo_names: List[str]) -> Dict[str, JobInfo]:
        """Start SWE-Bench jobs for multiple repositories concurrently (max {MAX_CONCURRENT_JOBS} at a time)."""
        print(f"🚀 Starting SWE-Bench jobs for {len(repo_names)} repositories (max {MAX_CONCURRENT_JOBS} concurrent)...")
        
        jobs_info = {}
        
        def start_single_job(repo_name: str) -> JobInfo:
            """Start a job for a single repository."""
            job_info = JobInfo(repo_name=repo_name, started_at=time.time())
            
            try:
                if self.config.retrigger_jobs:
                    print(f"🔄 Starting new job for {repo_name}")
                    job_id = self._start_job(repo_name.replace("/", "__"))
                else:
                    print(f"🔍 Checking existing job for {repo_name}")
                    job_id = self._get_job_id(repo_name.replace("/", "__"))
                    if not job_id:
                        print(f"🔄 No existing job, starting new one for {repo_name}")
                        job_id = self._start_job(repo_name.replace("/", "__"))
                    else:
                        print(f"♻️ Found existing job {job_id} for {repo_name}")
                
                if job_id:
                    job_info.job_id = job_id
                    job_info.status = 'in_progress'
                    print(f"✅ Job {job_id} started/found for {repo_name}")
                else:
                    job_info.status = 'failed'
                    job_info.error_message = 'Failed to start job'
                    print(f"❌ Failed to start job for {repo_name}")
                    
            except Exception as e:
                job_info.status = 'failed'
                job_info.error_message = str(e)
                print(f"❌ Error starting job for {repo_name}: {e}")
            
            return job_info
        
        # Use ThreadPoolExecutor to start jobs concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS) as executor:
            future_to_repo = {
                executor.submit(start_single_job, repo_name): repo_name 
                for repo_name in repo_names
            }
            
            for future in concurrent.futures.as_completed(future_to_repo):
                repo_name = future_to_repo[future]
                try:
                    job_info = future.result()
                    jobs_info[repo_name] = job_info
                except Exception as e:
                    jobs_info[repo_name] = JobInfo(
                        repo_name=repo_name,
                        status='failed',
                        error_message=f"Exception during job start: {e}",
                        started_at=time.time()
                    )
        
        successful_jobs = sum(1 for job in jobs_info.values() if job.status == 'in_progress')
        failed_jobs = len(jobs_info) - successful_jobs
        
        print(f"📊 Job start summary: {successful_jobs} started, {failed_jobs} failed")
        return jobs_info
    
    def monitor_jobs_completion(self, jobs_info: Dict[str, JobInfo]) -> Dict[str, JobInfo]:
        """Monitor multiple jobs until completion (max {MAX_CONCURRENT_JOBS} monitored concurrently)."""
        print(f"⏳ Monitoring {len(jobs_info)} jobs for completion (max {MAX_CONCURRENT_JOBS} concurrent)...")
        
        completed_jobs = {}
        remaining_jobs = {k: v for k, v in jobs_info.items() if v.status == 'in_progress'}
        
        def check_job_completion(repo_name: str, job_info: JobInfo) -> JobInfo:
            """Check if a single job is complete."""
            if not job_info.job_id:
                job_info.status = 'failed'
                job_info.completed_at = time.time()
                return job_info
            
            try:
                while True:
                    status = self._get_job_status(job_info.job_id)
                    
                    if status == "COMPLETED":
                        job_info.status = 'completed'
                        job_info.completed_at = time.time()
                        duration = job_info.completed_at - (job_info.started_at or 0)
                        print(f"✅ Job completed for {repo_name} (Duration: {duration:.1f}s)")
                        break
                    elif status in {"FAILED", "CANCELLED"}:
                        job_info.status = 'failed'
                        job_info.error_message = f'Job {status.lower()}'
                        job_info.completed_at = time.time()
                        print(f"❌ Job {status.lower()} for {repo_name}")
                        break
                    
                    # Wait before checking again
                    time.sleep(10)
                    
            except Exception as e:
                job_info.status = 'failed'
                job_info.error_message = str(e)
                job_info.completed_at = time.time()
                print(f"❌ Error monitoring job for {repo_name}: {e}")
            
            return job_info
        
        # Monitor all jobs concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS) as executor:
            future_to_repo = {
                executor.submit(check_job_completion, repo_name, job_info): repo_name
                for repo_name, job_info in remaining_jobs.items()
            }
            
            # Add jobs that were already failed during start
            for repo_name, job_info in jobs_info.items():
                if job_info.status == 'failed':
                    completed_jobs[repo_name] = job_info
            
            # Collect completed jobs as they finish
            for future in concurrent.futures.as_completed(future_to_repo):
                repo_name = future_to_repo[future]
                try:
                    job_info = future.result()
                    completed_jobs[repo_name] = job_info
                    
                    # Show progress
                    completed_count = len(completed_jobs)
                    total_count = len(jobs_info)
                    print(f"📈 Progress: {completed_count}/{total_count} jobs completed")
                    
                except Exception as e:
                    completed_jobs[repo_name] = JobInfo(
                        repo_name=repo_name,
                        status='failed',
                        error_message=f"Exception during monitoring: {e}",
                        started_at=remaining_jobs[repo_name].started_at,
                        completed_at=time.time()
                    )
        
        # Wait a bit for webpage data to load for completed jobs
        time.sleep(3)
        
        successful_jobs = sum(1 for job in completed_jobs.values() if job.status == 'completed')
        failed_jobs = len(completed_jobs) - successful_jobs
        
        print(f"📊 Job completion summary: {successful_jobs} completed, {failed_jobs} failed")
        return completed_jobs

# ---------------------------------------------------------------------------
# Data Processor
# ---------------------------------------------------------------------------

class DataProcessor:
    """Handles data processing, filtering, and CSV generation."""
    
    def __init__(self, config: ProcessingConfig):
        self.config = config
    
    def process_pr_data(self, pr_rows: List[Dict], repo_name: str) -> List[Dict]:
        """Process and clean PR data."""
        processed_rows = []
        
        for row in pr_rows:
            if not isinstance(row, dict):
                continue
            
            processed_row = row.copy()
            
            # Add repo field if not present
            if 'repo' not in processed_row:
                processed_row['repo'] = repo_name
            
            # Ensure required fields
            if 'instance_id' in processed_row and processed_row['instance_id']:
                instance_id = str(processed_row['instance_id'])
                
                if 'swe_url' not in processed_row or not processed_row['swe_url']:
                    processed_row['swe_url'] = f"https://swe-bench-plus.turing.com/instances/{instance_id}"
                
                if 'pr_id' not in processed_row or not processed_row['pr_id']:
                    processed_row['pr_id'] = instance_id
            
            processed_rows.append(processed_row)
        
        return processed_rows
    
    def save_and_convert_data(self, pr_data: List[Dict], repo_name: str) -> Tuple[bool, RepositoryStats]:
        """Save JSON data and convert to CSV, returning success status and stats."""
        repo_safe = repo_name.replace("/", "__")
        stats = RepositoryStats(repository=repo_name, initial_pr_count=len(pr_data))
        
        # Save JSON
        json_path = os.path.join(self.config.json_folder, f"{repo_safe}_pr_data.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(pr_data, f, indent=2)
            print(f"💾 Saved JSON ⇒ {json_path} ({len(pr_data)} PRs)")
        except Exception as e:
            stats.error_message = f"Failed to save JSON: {e}"
            return False, stats
        
        # Convert to CSV
        csv_path = os.path.join(self.config.csv_folder, f"{repo_safe}_pr_data.csv")
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            result = process_json_file(
                input_file=json_path,
                output_file=csv_path,
                existing_repos=set(),
                force=False,
                base_dir=base_dir,
                language=self.config.language,
                upload_mode=self.config.upload_mode,
            )
            
            if not isinstance(result, dict) or not result.get('success'):
                stats.error_message = f"CSV conversion failed: {result}"
                return False, stats
            
            # Update stats from conversion result
            stats.after_date_filter_count = result.get('after_date_filter_count', 0)
            stats.logical_pr_count = result.get('logical_pr_count', 0)
            stats.good_pr_count = result.get('good_pr_count', 0)
            stats.final_pr_count = result.get('final_pr_count', 0)
            stats.uploaded_pr_count = result.get('uploaded_pr_count', 0)
            stats.missing_pr_ids = result.get('missing_pr_ids', [])
            stats.success = True
            
            print(f"💾 Saved CSV ⇒ {csv_path} ({stats.final_pr_count} usable PRs)")
            
            return stats.final_pr_count > 0, stats
            
        except Exception as e:
            stats.error_message = f"CSV conversion error: {e}"
            return False, stats

# ---------------------------------------------------------------------------
# Labeling Tool Integration
# ---------------------------------------------------------------------------

class LabelingToolClient:
    """Handles Labeling Tool batch creation and repo checking."""
    
    def __init__(self, config: ProcessingConfig):
        self.config = config
        self.lt_token = get_lt_token()
        self.existing_repos_cache: Optional[Set[str]] = None
    
    def _make_lt_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """Make request to Labeling Tool API."""
        headers = kwargs.setdefault("headers", {})
        headers.update({"Authorization": f"Bearer {self.lt_token}"})
        
        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            print(f"❌ LT API error: {e}")
            return None
    
    def get_existing_repos(self) -> Set[str]:
        """Get all existing repository names from Labeling Tool."""
        if self.existing_repos_cache is not None:
            return self.existing_repos_cache
        
        print(f"🔍 Fetching existing repos from LT project {self.config.project_id}...")
        
        base_url = f"https://eval.turing.com/api/batches"
        params = {
            'sort[0]': 'createdAt,DESC',
            'join[0]': 'batchStats',
            'join[1]': 'importAttempts', 
            f'filter[0]': f'projectId||$eq||{self.config.project_id}',
            'limit': 100,
            'page': 1
        }
        
        existing_repos = set()
        page = 1
        
        while True:
            params['page'] = page
            response = self._make_lt_request("get", base_url, params=params)
            
            if not response:
                break
            
            data = response.json()
            batches = data.get("data", [])
            
            if not batches:
                break
            
            for batch in batches:
                batch_name = batch.get("name", "")
                if batch_name:
                    existing_repos.add(batch_name)
            
            if len(batches) < 100:
                break
            
            page += 1
        
        self.existing_repos_cache = existing_repos
        print(f"✅ Found {len(existing_repos)} existing repos in LT")
        return existing_repos
    
    def check_repo_exists(self, repo_name: str) -> Tuple[bool, Optional[str]]:
        """Check if repository exists in LT (including part files)."""
        lt_repo_name = repo_name.replace("/", "__")
        existing_repos = self.get_existing_repos()
        
        # Check exact match
        if lt_repo_name in existing_repos:
            return True, lt_repo_name
        
        # Check part files
        part_files = [repo for repo in existing_repos if repo.startswith(lt_repo_name + "_PART_")]
        if part_files:
            return True, part_files[0]
        
        # Check __Public suffix
        public_name = lt_repo_name + "__Public"
        if public_name in existing_repos:
            return True, public_name
        
        return False, None
    
    def create_batch(self, repo_safe_name: str, csv_path: str) -> Optional[str]:
        """Create a new batch in Labeling Tool."""
        # repo_safe_name is already in safe format (might include PART suffix)
        repo_safe = repo_safe_name
        
        # Upload file
        upload_url = "https://eval.turing.com/api/batches/upload/rlhf-metadata"
        with open(csv_path, "rb") as f:
            upload_response = self._make_lt_request(
                "post", upload_url,
                data={"project_type": "rlhf"},
                files={"file": f}
            )
        
        if not upload_response:
            raise Exception("Failed to upload CSV to LT")
        
        file_link = upload_response.json()["fileLink"]
        
        # Create batch
        create_url = "https://eval.turing.com/api/batches"
        batch_payload = {
            "name": repo_safe,
            "folder": file_link,
            "description": "",
            "status": "draft",
            "file": {},
            "isRLHFFolder": False,
            "shouldShowSubfolder": False,
            "isRLHFProjectSuite": True,
            "project": {
                "id": self.config.project_id,
                "name": f"Swe-bench-{self.config.language}",
                "status": "ongoing",
                "projectType": "rlhf",
                "readonly": False,
            },
            "projectId": self.config.project_id,
            "projectType": "rlhf",
        }
        
        create_response = self._make_lt_request("post", create_url, json=batch_payload)
        if not create_response:
            raise Exception("Failed to create batch in LT")
        
        batch_id = create_response.json()["id"]
        
        # Trigger import
        import_url = f"https://eval.turing.com/api/batches/{batch_id}/import-rlhf"
        import_response = self._make_lt_request("post", import_url, json=batch_payload)
        if not import_response:
            raise Exception("Failed to trigger import in LT")
        
        return f"https://eval.turing.com/batches/{batch_id}/view"
    
    def get_existing_pr_ids_for_repo(self, repo_name: str) -> Set[str]:
        """Fetch existing PR IDs for a specific repository from the labeling tool."""
        print(f"🔍 Fetching existing PR IDs for repo: {repo_name}")
        
        existing_pr_ids = set()
        
        # First, find all batches for this repository (including part files)
        base_url = f"https://eval.turing.com/api/batches"
        params = {
            'sort[0]': 'createdAt,DESC',
            'join[0]': 'batchStats',
            'join[1]': 'importAttempts', 
            f'filter[0]': f'projectId||$eq||{self.config.project_id}',
            'limit': 100,
            'page': 1
        }
        
        try:
            matching_batches = []
            page = 1
            
            while True:
                params['page'] = page
                response = self._make_lt_request("get", base_url, params=params)
                if not response:
                    break
                    
                data = response.json()
                batches = data.get("data", [])
                if not batches:
                    break
                
                # Find batches that match the repo name (including part files)
                for batch in batches:
                    batch_name = batch.get("name", "")
                    if batch_name.startswith(repo_name):
                        matching_batches.append(batch)
                        print(f"   📋 Found matching batch: {batch_name}")
                
                if len(batches) < 100:
                    break
                page += 1
            
            # Fetch conversations (PRs) for each matching batch
            for batch in matching_batches:
                batch_id = batch.get("id")
                if not batch_id:
                    continue
                    
                print(f"   📄 Fetching PRs from batch {batch_id} ({batch.get('name', 'Unknown')})...")
                
                # Fetch conversations for this batch
                conv_url = f"https://eval.turing.com/api/conversations"
                conv_params = {
                    'join[0]': 'project||id,name',
                    'join[1]': 'batch||id,name',
                    'join[2]': 'seed||metadata',
                    f'filter[0]': f'batchId||$in||{batch_id}',
                    'limit': 100,
                    'page': 1
                }
                
                conv_page = 1
                while True:
                    conv_params['page'] = conv_page
                    
                    try:
                        conv_response = self._make_lt_request("get", conv_url, params=conv_params)
                        if not conv_response:
                            break
                            
                        conv_data = conv_response.json()
                        conversations = conv_data.get("data", [])
                        
                        if not conversations:
                            break
                        
                        # Extract PR IDs from conversations
                        for conv in conversations:
                            pr_id = conv.get("seed", {}).get("metadata", {}).get("pr_id")
                            if pr_id:
                                existing_pr_ids.add(str(pr_id))
                        
                        if len(conversations) < 100:
                            break
                            
                        conv_page += 1
                        
                    except Exception as e:
                        print(f"   ❌ Error fetching conversations for batch {batch_id}: {e}")
                        break
            
            print(f"   ✅ Found {len(existing_pr_ids)} existing PR IDs for repo {repo_name}")
            
        except Exception as e:
            print(f"   ❌ Error fetching batches: {e}")
        
        return existing_pr_ids
    
    def compare_prs_and_check_for_new(self, repo_name: str, csv_path: str) -> Tuple[bool, int]:
        """
        Compare PRs in CSV with existing PRs in LT and return if there are new PRs.
        
        Returns:
            Tuple of (has_new_prs, new_pr_count)
        """
        print(f"🔍 Comparing PRs for {repo_name}...")
        
        # Get existing PR IDs from LT
        existing_pr_ids = self.get_existing_pr_ids_for_repo(repo_name)
        
        if not existing_pr_ids:
            print(f"   ✅ No existing PRs found in LT, all PRs are new")
            # Count PRs in CSV to return the count
            csv_pr_count = 0
            try:
                with open(csv_path, 'r', encoding='utf-8') as csv_file:
                    reader = csv.reader(csv_file)
                    next(reader)  # Skip header
                    csv_pr_count = sum(1 for row in reader if row)
            except Exception:
                pass
            return True, csv_pr_count
        
        # Read PR IDs from CSV file
        csv_pr_ids = set()
        try:
            with open(csv_path, 'r', encoding='utf-8') as csv_file:
                reader = csv.reader(csv_file)
                next(reader)  # Skip header
                
                for row in reader:
                    if row and len(row) > 0:
                        try:
                            metadata = json.loads(row[0])
                            pr_id = metadata.get("pr_id")
                            if pr_id:
                                csv_pr_ids.add(str(pr_id))
                        except (json.JSONDecodeError, KeyError):
                            continue
        except Exception as e:
            print(f"   ❌ Error reading CSV file: {e}")
            return False, 0
        
        print(f"   📊 CSV contains {len(csv_pr_ids)} PRs")
        print(f"   📊 LT contains {len(existing_pr_ids)} PRs")
        
        # Check for new PRs
        new_prs = csv_pr_ids - existing_pr_ids
        new_pr_count = len(new_prs)
        
        if new_pr_count == 0:
            print(f"   ⚠️ All PRs in CSV already exist in LT")
            return False, 0
        
        print(f"   ✅ Found {new_pr_count} new PRs to upload")
        return True, new_pr_count

# ---------------------------------------------------------------------------
# Repository Source Management
# ---------------------------------------------------------------------------

class RepositorySource:
    """Manages repository source (manual list or Google Sheets)."""
    
    def __init__(self, config: ProcessingConfig):
        self.config = config
    
    def get_repositories(self) -> List[str]:
        """Get repository list from configured source."""
        if self.config.use_manual_repos:
            return self._get_manual_repos()
        else:
            return self._get_sheet_repos()
    
    def _get_manual_repos(self) -> List[str]:
        """Get repositories from manual list."""
        print(f"📋 Using manual repository list: {len(self.config.manual_repos)} repos")
        return self.config.manual_repos
    
    def _get_sheet_repos(self) -> List[str]:
        """Get repositories from Google Sheets."""
        print(f"🔍 Fetching repositories from sheet: {self.config.sheet_name}")
        
        try:
            client = _get_gspread_client()
            df, header = fetch_sheet_data(self.config.sheet_name, client)
            
            if df.empty:
                print("❌ Sheet is empty")
                return []
            
            column_indices = get_column_indices(header)
            
            # Filter qualifying repositories
            repo_col = column_indices.get('repository', 0)
            good_prs_col = column_indices.get('good_prs_gt_2', 9)
            added_col = column_indices.get('added', 10)
            relevant_prs_col = column_indices.get('relevant_prs_count', 8)
            
            qualifying_repos = []
            for _, row in df.iterrows():
                if (len(row) > max(repo_col, good_prs_col, added_col) and
                    row[good_prs_col] == 'Yes' and 
                    row[added_col] == 'No' and
                    row[repo_col].strip()):
                    qualifying_repos.append(row[repo_col].strip())
            
            # Sort by relevant PRs count if available
            if len(df.columns) > relevant_prs_col:
                try:
                    repo_relevance = []
                    for repo in qualifying_repos:
                        repo_rows = df[df.iloc[:, repo_col] == repo]
                        if not repo_rows.empty:
                            relevance = pd.to_numeric(repo_rows.iloc[0, relevant_prs_col], errors='coerce')
                            repo_relevance.append((repo, relevance or 0))
                    
                    # Sort by relevance (descending)
                    repo_relevance.sort(key=lambda x: x[1], reverse=True)
                    qualifying_repos = [repo for repo, _ in repo_relevance]
                except Exception as e:
                    print(f"⚠️ Could not sort by relevance: {e}")
            
            print(f"✅ Found {len(qualifying_repos)} qualifying repositories")
            return qualifying_repos
            
        except Exception as e:
            print(f"❌ Error fetching from Google Sheet: {e}")
            return []
    
    def update_repo_status(self, repo_name: str, status: str = "Yes") -> bool:
        """Update repository status in Google Sheets."""
        if self.config.use_manual_repos:
            return True  # No update needed for manual repos
        
        try:
            client = _get_gspread_client()
            df, header = fetch_sheet_data(self.config.sheet_name, client)
            column_indices = get_column_indices(header)
            
            repo_col = column_indices.get('repository', 0)
            added_col = column_indices.get('added', 10)
            
            # Find repository row
            repo_row = None
            for idx, row in df.iterrows():
                if len(row) > repo_col and row[repo_col] == repo_name:
                    repo_row = idx + 2  # Convert to 1-based + header
                    break
            
            if repo_row is None:
                print(f"⚠️ Repository {repo_name} not found in sheet")
                return False
            
            # Update cell
            import gspread
            sheet = client.open_by_key(get_google_sheet()).worksheet(self.config.sheet_name)
            col_letter = chr(65 + added_col)  # Convert to Excel column
            cell_address = f"{col_letter}{repo_row}"
            
            cell_update = gspread.Cell(repo_row, added_col + 1, status)
            update_sheet_cells(self.config.sheet_name, [cell_update], client)
            
            print(f"📝 Updated {repo_name} status to '{status}'")
            return True
            
        except Exception as e:
            print(f"❌ Error updating sheet: {e}")
            return False

# ---------------------------------------------------------------------------
# Report Generator
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Generates processing reports and statistics."""
    
    def __init__(self, config: ProcessingConfig):
        self.config = config
    
    def generate_report(self, summary: ProcessingSummary) -> str:
        """Generate comprehensive processing report."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        reports_dir = os.path.join(base_dir, "processing_reports")
        os.makedirs(reports_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(reports_dir, f"batch_processing_v3_{timestamp}.csv")
        
        # Calculate totals
        total_pr_total = sum(stat.initial_pr_count for stat in summary.repository_stats)
        total_after_date = sum(stat.after_date_filter_count for stat in summary.repository_stats)
        total_logical = sum(stat.logical_pr_count for stat in summary.repository_stats)
        total_good = sum(stat.good_pr_count for stat in summary.repository_stats)
        total_uploaded = sum(stat.uploaded_pr_count for stat in summary.repository_stats)
        total_missing = sum(len(stat.missing_pr_ids) for stat in summary.repository_stats)
        
        # Write report
        import csv
        with open(report_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Summary header
            writer.writerow(['SWE-BENCH BATCH PROCESSING REPORT V3'])
            writer.writerow([f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'])
            writer.writerow([f'Language: {self.config.language}'])
            writer.writerow([f'Project ID: {self.config.project_id}'])
            writer.writerow([f'Upload Mode: {self.config.upload_mode}'])
            writer.writerow([f'Target Count: {self.config.target_count}'])
            writer.writerow([])
            
            # Summary statistics
            writer.writerow(['SUMMARY STATISTICS'])
            writer.writerow(['Total Repositories', summary.total_repos])
            writer.writerow(['Successful Uploads', summary.successful_repos])
            writer.writerow(['Failed', summary.failed_repos])
            writer.writerow(['Skipped (existing)', summary.skipped_repos])
            writer.writerow([f'Skipped (insufficient PRs, min {MIN_PRS_FOR_UPLOAD})', summary.no_prs_repos])
            writer.writerow([])
            
            # PR totals
            writer.writerow(['PR TOTALS'])
            writer.writerow(['Total PRs', 'After Date Filter', 'Logical PRs', 'Good PRs', 'Uploaded PRs', 'Missing PRs'])
            writer.writerow([total_pr_total, total_after_date, total_logical, total_good, total_uploaded, total_missing])
            writer.writerow([])
            
            # Detailed stats
            writer.writerow(['DETAILED REPOSITORY STATISTICS'])
            writer.writerow([
                'Repository', 'Status', 'Initial PRs', 'After Date Filter', 
                'Logical PRs', 'Good PRs', 'Final PRs', 'Uploaded PRs', 
                'Missing PRs', 'Missing PR IDs', 'Error Message'
            ])
            
            for stat in summary.repository_stats:
                writer.writerow([
                    stat.repository, stat.status, stat.initial_pr_count,
                    stat.after_date_filter_count, stat.logical_pr_count,
                    stat.good_pr_count, stat.final_pr_count, stat.uploaded_pr_count,
                    len(stat.missing_pr_ids), ', '.join(stat.missing_pr_ids),
                    stat.error_message
                ])
        
        print(f"\n📊 Processing report saved: {report_path}")
        self._print_summary(summary)
        
        return report_path
    
    def _print_summary(self, summary: ProcessingSummary):
        """Print processing summary to console."""
        print("\n" + "=" * 80)
        print("📊 PROCESSING SUMMARY")
        print("=" * 80)
        print(f"Language: {self.config.language}")
        print(f"Target repositories: {self.config.target_count}")
        print(f"Successfully processed: {summary.successful_repos}")
        
        # Count part files
        part_files = sum(1 for stat in summary.repository_stats if stat.status == 'success_part_file')
        if part_files > 0:
            print(f"  └─ Part files created: {part_files}")
        
        print(f"Failed: {summary.failed_repos}")
        print(f"Skipped (existing): {summary.skipped_repos}")
        print(f"Skipped (insufficient PRs, min {MIN_PRS_FOR_UPLOAD}): {summary.no_prs_repos}")
        print(f"Total PRs processed: {summary.total_prs_processed}")
        print(f"Total PRs uploaded: {summary.total_prs_uploaded}")
        print("=" * 80)

# ---------------------------------------------------------------------------
# Main Repository Processor
# ---------------------------------------------------------------------------

class RepositoryProcessor:
    """Main orchestrator for repository processing."""
    
    def __init__(self, config: ProcessingConfig):
        self.config = config
        self.swe_client = SWEBenchClient(config)
        self.data_processor = DataProcessor(config)
        self.lt_client = LabelingToolClient(config)
        self.repo_source = RepositorySource(config)
        self.report_generator = ReportGenerator(config)
        
        print(f"🚀 Repository Processor V3 initialized")
        print(f"   Language: {config.language}")
        print(f"   Upload Mode: {config.upload_mode}")
        print(f"   Target Count: {config.target_count}")
        print(f"   Source: {'Manual' if config.use_manual_repos else 'Google Sheets'}")
        print(f"   Re-trigger Jobs: {'Yes' if config.retrigger_jobs else 'No (use existing)'}")
    
    def process_repositories(self) -> ProcessingSummary:
        """Process all repositories using async job management for better performance."""
        summary = ProcessingSummary()
        
        # Get repository list
        repositories = self.repo_source.get_repositories()
        if not repositories:
            print("❌ No repositories to process")
            return summary
        
        summary.total_repos = len(repositories)
        print(f"\n🎯 Processing {len(repositories)} repositories with async job management...")
        
        # Phase 1: Start all SWE-Bench jobs concurrently
        print(f"\n📋 Phase 1: Starting SWE-Bench jobs...")
        jobs_info = self.swe_client.start_multiple_jobs(repositories)
        
        # Phase 2: Monitor jobs and process as they complete
        print(f"\n📋 Phase 2: Monitoring jobs and processing completed ones...")
        completed_jobs = self.swe_client.monitor_jobs_completion(jobs_info)
        
        # Phase 3: Process repository data as jobs complete
        print(f"\n📋 Phase 3: Processing repository data...")
        processed_count = 0
        
        for repo_name, job_info in completed_jobs.items():
            if summary.successful_repos >= self.config.target_count:
                print(f"🎯 Reached target of {self.config.target_count} repositories")
                break
                
            print(f"\n--- Processing {processed_count + 1}/{len(repositories)}: {repo_name} ---")
            
            try:
                # Process the repository data (skip the job creation part)
                stats = self._process_repository_data(repo_name, job_info)
                summary.repository_stats.append(stats)
                
                # Update counters
                if stats.status == 'success':
                    summary.successful_repos += 1
                    summary.total_prs_uploaded += stats.uploaded_pr_count
                elif stats.status == 'success_part_file':
                    summary.successful_repos += 1
                    summary.total_prs_uploaded += stats.uploaded_pr_count
                elif stats.status == 'failed':
                    summary.failed_repos += 1
                elif stats.status == 'skipped_existing':
                    summary.skipped_repos += 1
                elif stats.status == 'skipped_no_prs':
                    summary.no_prs_repos += 1
                
                summary.total_prs_processed += stats.initial_pr_count
                processed_count += 1
                
            except Exception as e:
                print(f"❌ Unexpected error processing {repo_name}: {e}")
                error_stats = RepositoryStats(
                    repository=repo_name,
                    status='failed',
                    error_message=f"Unexpected error: {e}"
                )
                summary.repository_stats.append(error_stats)
                summary.failed_repos += 1
                processed_count += 1
        
        # Generate report
        self.report_generator.generate_report(summary)
        
        return summary
    
    def _process_repository_data(self, repo_name: str, job_info: JobInfo) -> RepositoryStats:
        """Process a single repository."""
        stats = RepositoryStats(repository=repo_name)
        
        try:
            # 1. Check job status (jobs were already started and monitored async)
            if job_info.status != 'completed':
                stats.status = 'failed'
                stats.error_message = job_info.error_message or f'SWE-Bench job {job_info.status}'
                return stats
            
            # 2. Get PR data (job is already completed)
            pr_data = self.swe_client.get_pr_data_from_webpage(repo_name)
            if not pr_data:
                stats.status = 'failed'
                stats.error_message = 'No PR data found'
                return stats
            
            stats.initial_pr_count = len(pr_data)
            
            # 3. Process and convert data
            processed_data = self.data_processor.process_pr_data(pr_data, repo_name)
            has_usable_prs, conversion_stats = self.data_processor.save_and_convert_data(
                processed_data, repo_name
            )
            
            # Update stats from conversion
            stats.after_date_filter_count = conversion_stats.after_date_filter_count
            stats.logical_pr_count = conversion_stats.logical_pr_count
            stats.good_pr_count = conversion_stats.good_pr_count
            stats.final_pr_count = conversion_stats.final_pr_count
            stats.uploaded_pr_count = conversion_stats.uploaded_pr_count
            stats.missing_pr_ids = conversion_stats.missing_pr_ids
            stats.success = conversion_stats.success
            
            if not has_usable_prs or stats.final_pr_count < MIN_PRS_FOR_UPLOAD:
                stats.status = 'skipped_no_prs'
                if stats.final_pr_count == 0:
                    print(f"⚠️ No usable PRs for {repo_name}, skipping upload")
                else:
                    print(f"⚠️ Only {stats.final_pr_count} usable PR(s) for {repo_name}, minimum {MIN_PRS_FOR_UPLOAD} required, skipping upload")
                return stats
            
            # 4. Check if already exists in LT and handle deduplication
            # Logic: If repo exists, compare PR IDs to check for new PRs
            # If new PRs found, create a PART file with suffix (e.g., repo_PART_002)
            exists, existing_name = self.lt_client.check_repo_exists(repo_name)
            
            # Default paths (will be updated if part files are needed)
            repo_safe = repo_name.replace('/', '__')
            csv_path = os.path.join(self.config.csv_folder, f"{repo_safe}_pr_data.csv")
            json_path = os.path.join(self.config.json_folder, f"{repo_safe}_pr_data.json")
            
            if exists:
                print(f"🔍 Repository {repo_name} exists in LT as {existing_name}")
                
                # Compare PRs to check for new ones
                has_new_prs, new_pr_count = self.lt_client.compare_prs_and_check_for_new(
                    existing_name, csv_path
                )
                
                if not has_new_prs:
                    print(f"⏭️ Skipping upload for {repo_name} - all PRs already exist in LT")
                    stats.status = 'skipped_existing'
                    # Update sheet status
                    self.repo_source.update_repo_status(repo_name, "Yes")
                    return stats
                else:
                    print(f"✅ Proceeding with upload for {repo_name} - {new_pr_count} new PRs found")
                    
                    # Determine next PART suffix
                    part_match = re.search(r"_PART_(\d{3})$", existing_name)
                    if part_match:
                        # Remove existing PART suffix to get base name
                        base_repo_name = existing_name[:part_match.start()]
                        existing_part_num = int(part_match.group(1))
                        next_part_num = existing_part_num + 1
                    else:
                        # No existing PART suffix, use the full name as base
                        base_repo_name = existing_name
                        next_part_num = 2  # Start with PART_002 for first additional batch
                    
                    suffix_part = f"_PART_{next_part_num:03d}"
                    repo_safe_with_suffix = base_repo_name + suffix_part
                    
                    # Update paths with suffix
                    csv_path_new = os.path.join(self.config.csv_folder, f"{repo_safe_with_suffix}_pr_data.csv")
                    json_path_new = os.path.join(self.config.json_folder, f"{repo_safe_with_suffix}_pr_data.json")
                    
                    # Rename the generated JSON/CSV to the new names
                    try:
                        os.rename(json_path, json_path_new)
                        os.rename(csv_path, csv_path_new)
                        print(f"📝 Renamed files with suffix: {suffix_part}")
                    except Exception as e:
                        print(f"⚠️ Warning: Could not rename files: {e}")
                        # Continue with original names if rename fails
                        json_path_new = json_path
                        csv_path_new = csv_path
                        repo_safe_with_suffix = repo_safe
                    
                    # Update paths and repo name for upload
                    csv_path = csv_path_new
                    json_path = json_path_new
                    repo_safe = repo_safe_with_suffix
            
            # 5. Upload to LT
            
            batch_url = self.lt_client.create_batch(repo_safe, csv_path)
            print(f"✅ Batch created: {batch_url}")
            
            # Update sheet status
            self.repo_source.update_repo_status(repo_name, "Yes")
            
            # Set appropriate status based on whether this was a part file
            if exists and "_PART_" in repo_safe:
                stats.status = 'success_part_file'
                print(f"✅ Part file successfully created and uploaded for {repo_name}")
            else:
                stats.status = 'success'
            
            # Update uploaded count (already set during conversion, but ensure consistency)
            stats.uploaded_pr_count = stats.final_pr_count
            
            return stats
            
        except Exception as e:
            stats.status = 'failed'
            stats.error_message = str(e)
            print(f"❌ Error processing {repo_name}: {e}")
            return stats

# ---------------------------------------------------------------------------
# Command Line Interface
# ---------------------------------------------------------------------------

def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="SWE-Bench Batch Creator V3",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        'language',
        help='Target language (e.g., JavaScript, Python, Java)'
    )
    
    parser.add_argument(
        '--manual', nargs='*',
        help='Manual repository list (e.g., --manual user/repo1 user/repo2)'
    )
    
    parser.add_argument(
        '--count', type=int, default=30,
        help='Target number of repositories to process (default: 30)'
    )
    
    parser.add_argument(
        '--upload-mode', choices=['All', 'Good', 'Logical'], default='Logical',
        help='Upload filtering mode (default: Logical)'
    )
    
    parser.add_argument(
        '--no-retrigger', action='store_true',
        help='Do not re-trigger SWE-Bench jobs, use existing completed jobs if available'
    )
    
    return parser.parse_args()

def main():
    """Main entry point."""
    # Check if running with command line arguments or direct execution
    if len(sys.argv) == 1:
        # Direct execution - use configuration from top of script
        print("🚀 Running with configuration from script constants (no command line args provided)")
        config = ProcessingConfig(
            language=LANGUAGE,
            target_count=TARGET_COUNT,
            upload_mode=UPLOAD_MODE,
            use_manual_repos=USE_MANUAL_REPOS,
            manual_repos=MANUAL_REPOS,
            retrigger_jobs=RETRIGGER_JOBS
        )
    else:
        # Command line execution - parse arguments
        args = parse_arguments()
        config = ProcessingConfig(
            language=args.language,
            target_count=args.count,
            upload_mode=args.upload_mode,
            use_manual_repos=args.manual is not None,
            manual_repos=args.manual or [],
            retrigger_jobs=not args.no_retrigger  # Default True unless --no-retrigger specified
        )
    
    print("=== SWE-Bench Batch Creator V3 ===")
    print(f"Language: {config.language}")
    print(f"Upload Mode: {config.upload_mode}")
    print(f"Target Count: {config.target_count}")
    print(f"Source: {'Manual repos' if config.use_manual_repos else 'Google Sheets'}")
    print(f"Re-trigger Jobs: {'Yes' if config.retrigger_jobs else 'No (use existing)'}")
    print("=" * 50)
    
    # Clear cache for fresh data
    try:
        cache = FanoutCache("cache")
        cache.clear()
        print("🧹 Cache cleared")
    except Exception as e:
        print(f"⚠️ Could not clear cache: {e}")
    
    # Process repositories
    processor = RepositoryProcessor(config)
    summary = processor.process_repositories()
    
    print(f"\n🎉 Processing complete!")
    print(f"Processed {summary.successful_repos}/{config.target_count} target repositories")

if __name__ == "__main__":
    main() 
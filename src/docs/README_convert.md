# Data Format Converter & Processor

## Overview

`convert.py` is a comprehensive data processing tool that converts JSON PR data to CSV format while enriching it with metadata, statistics, and quality metrics. It handles batch processing, generates detailed reports, and manages data organization across multiple languages and repositories.

## Features

### 🔄 Format Conversion
- **JSON to CSV**: Converts structured JSON data to tabular CSV format
- **Data Enrichment**: Adds metadata, statistics, and processing information
- **Batch Processing**: Handles multiple files and directories efficiently
- **Language-aware Processing**: Supports all configured programming languages

### 📊 Report Generation
- **Processing Reports**: Detailed statistics about conversion process
- **Quality Metrics**: Analysis of data quality and completeness
- **Error Tracking**: Comprehensive error reporting and handling
- **Performance Stats**: Processing time and efficiency metrics

### 🔧 Data Management
- **Duplicate Prevention**: Checks against existing repositories and PR IDs
- **Validation**: Ensures data integrity during conversion
- **Organization**: Maintains proper directory structure by language
- **Cleanup**: Removes temporary files and manages storage

## Configuration

### Language Directory Structure
```python
# Directory mapping by language
LANGUAGE_DIRECTORIES = {
    'JavaScript': 'JavaScript_json',
    'Python': 'Python_json', 
    'Java': 'Java_json',
    'Rust': 'Rust_json',
    'Go': 'Go_json'
}

# Output directories
OUTPUT_DIRECTORIES = {
    'JavaScript': 'JavaScript_csv',
    'Python': 'Python_csv',
    'Java': 'Java_csv', 
    'Rust': 'Rust_csv',
    'Go': 'Go_csv'
}
```

### Processing Settings
```python
# Conversion settings
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB max file size
BATCH_SIZE = 1000                   # Records per batch
CHUNK_SIZE = 10000                  # Processing chunk size
TIMEOUT = 300                       # Processing timeout (seconds)

# Validation settings
REQUIRED_FIELDS = ['pr_id', 'pr_url', 'issue_id', 'issue_url']
OPTIONAL_FIELDS = ['agent_result', 'agent_comment', 'non_test_code_changes']
```

## Usage

### Command Line Interface

```bash
# Convert all language directories
python src/convert.py

# Convert specific language
python src/convert.py --language JavaScript

# Convert single file
python src/convert.py --input data.json --output result.csv

# Force reconversion
python src/convert.py --force

# Custom base directory
python src/convert.py --base-dir /path/to/data

# Verbose output
python src/convert.py --verbose
```

### Available Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--language` | Target language to convert | All languages |
| `--input` | Input JSON file path | Auto-detect |
| `--output` | Output CSV file path | Auto-generate |
| `--force` | Force reconversion of existing files | False |
| `--base-dir` | Base directory for processing | Current directory |
| `--verbose` | Detailed output | False |
| `--validate` | Validate data only (no conversion) | False |

### Programmatic Usage

```python
from src.convert import process_json_file, process_language_directories

# Convert single file
process_json_file(
    input_file="JavaScript_json/facebook__react_pr_data.json",
    output_file="JavaScript_csv/facebook__react_pr_data.csv",
    existing_repos=set(),
    force=False
)

# Convert all language directories
process_language_directories(
    base_dir=".",
    existing_repos=None,
    force=False
)
```

## Data Processing

### JSON Input Format
```json
[
  {
    "pr_id": 12345,
    "pr_url": "https://github.com/facebook/react/pull/12345",
    "issue_id": 67890,
    "issue_url": "https://github.com/facebook/react/issues/67890",
    "non_test_code_changes": 145,
    "agent_result": "Good PR",
    "agent_comment": "Clear feature implementation with good tests",
    "pr_title": "Add new component lifecycle method",
    "issue_title": "Feature request: Component lifecycle hooks",
    "merged_at": "2024-01-15T10:30:00Z",
    "created_at": "2024-01-10T09:15:00Z"
  }
]
```

### CSV Output Format
```csv
pr_id,pr_url,issue_id,issue_url,non_test_code_changes,agent_result,agent_comment,repo_name,processing_date,validation_status
12345,https://github.com/facebook/react/pull/12345,67890,https://github.com/facebook/react/issues/67890,145,Good PR,Clear feature implementation with good tests,facebook/react,2024-01-20T14:30:00Z,valid
```

### Data Enrichment
```python
def enrich_pr_data(pr_data, repo_name):
    """Enrich PR data with additional metadata."""
    enriched_data = pr_data.copy()
    
    # Add repository information
    enriched_data['repo_name'] = repo_name
    enriched_data['processing_date'] = datetime.now().isoformat()
    
    # Add validation status
    enriched_data['validation_status'] = validate_pr_data(pr_data)
    
    # Add quality metrics
    enriched_data['quality_score'] = calculate_quality_score(pr_data)
    
    # Add category classification
    enriched_data['category'] = classify_pr_category(pr_data)
    
    return enriched_data
```

## Batch Processing

### Directory Processing
```python
def process_language_directories(base_dir, existing_repos=None, force=False):
    """Process all language directories for conversion."""
    processing_stats = {}
    
    # Get all language configurations
    all_languages = get_all_language_configs()
    
    for language, config in all_languages.items():
        json_folder = config.get('json_folder')
        csv_folder = config.get('csv_folder')
        
        if json_folder and csv_folder:
            stats = process_directory(
                input_dir=os.path.join(base_dir, json_folder),
                output_dir=os.path.join(base_dir, csv_folder),
                existing_repos=existing_repos,
                force=force,
                language=language
            )
            processing_stats[language] = stats
    
    return processing_stats
```

### File Processing Pipeline
```python
def process_json_file(input_file, output_file, existing_repos=None, force=False):
    """Process single JSON file to CSV."""
    # 1. Validation
    if not validate_input_file(input_file):
        raise ValueError(f"Invalid input file: {input_file}")
    
    # 2. Load and parse JSON
    pr_data = load_json_data(input_file)
    
    # 3. Extract repository name
    repo_name = extract_repo_name_from_filename(input_file)
    
    # 4. Check for existing data
    if not force and output_file_exists(output_file):
        return skip_existing_file(output_file)
    
    # 5. Process and enrich data
    processed_data = []
    for pr in pr_data:
        enriched_pr = enrich_pr_data(pr, repo_name)
        processed_data.append(enriched_pr)
    
    # 6. Write CSV output
    write_csv_file(output_file, processed_data)
    
    # 7. Generate statistics
    return generate_processing_stats(processed_data, input_file, output_file)
```

## Data Validation

### Input Validation
```python
def validate_json_data(pr_data):
    """Validate JSON data structure and content."""
    validation_results = {
        'valid_records': 0,
        'invalid_records': 0,
        'errors': []
    }
    
    for index, pr in enumerate(pr_data):
        try:
            # Check required fields
            for field in REQUIRED_FIELDS:
                if field not in pr or not pr[field]:
                    raise ValueError(f"Missing required field: {field}")
            
            # Validate data types
            validate_data_types(pr)
            
            # Validate URLs
            validate_urls(pr)
            
            validation_results['valid_records'] += 1
            
        except Exception as e:
            validation_results['invalid_records'] += 1
            validation_results['errors'].append({
                'record_index': index,
                'error': str(e),
                'data': pr
            })
    
    return validation_results
```

### Data Type Validation
```python
def validate_data_types(pr_data):
    """Validate data types for PR fields."""
    # Validate integers
    if 'pr_id' in pr_data:
        if not isinstance(pr_data['pr_id'], int):
            raise TypeError("pr_id must be integer")
    
    # Validate URLs
    url_fields = ['pr_url', 'issue_url']
    for field in url_fields:
        if field in pr_data:
            if not is_valid_url(pr_data[field]):
                raise ValueError(f"Invalid URL format: {field}")
    
    # Validate enums
    if 'agent_result' in pr_data:
        valid_results = ['Good PR', 'Bad PR', 'Not Checked']
        if pr_data['agent_result'] not in valid_results:
            raise ValueError(f"Invalid agent_result: {pr_data['agent_result']}")
```

## Duplicate Management

### Existing Repository Check
```python
def get_existing_repos_set():
    """Get set of existing repositories from labeling tool."""
    existing_repos = set()
    
    # Fetch from multiple sources
    all_project_ids = get_all_project_ids()
    
    for project_id in all_project_ids:
        repos = fetch_existing_repos_for_project(project_id)
        existing_repos.update(repos)
    
    return existing_repos
```

### PR ID Deduplication
```python
def get_existing_pr_ids_for_repo(repo_name):
    """Get existing PR IDs for a repository."""
    try:
        # Check in labeling tool
        lt_pr_ids = get_existing_pr_ids_from_lt(repo_name)
        
        # Check in existing CSV files
        csv_pr_ids = get_existing_pr_ids_from_csv(repo_name)
        
        # Combine and return
        return lt_pr_ids.union(csv_pr_ids)
        
    except Exception as e:
        print(f"Warning: Could not fetch existing PR IDs for {repo_name}: {e}")
        return set()
```

### Duplicate Filtering
```python
def filter_duplicate_prs(pr_data, existing_pr_ids):
    """Filter out duplicate PRs based on existing IDs."""
    filtered_data = []
    duplicates_found = 0
    
    for pr in pr_data:
        pr_id = pr.get('pr_id')
        
        if pr_id and pr_id in existing_pr_ids:
            duplicates_found += 1
            continue
        
        filtered_data.append(pr)
    
    return filtered_data, duplicates_found
```

## Report Generation

### Processing Reports
```python
def create_processing_report(processing_stats, base_dir):
    """Create comprehensive processing report."""
    # Create processing_reports directory
    reports_dir = os.path.join(base_dir, "processing_reports")
    os.makedirs(reports_dir, exist_ok=True)
    
    # Generate timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"processing_report_{timestamp}.csv"
    report_path = os.path.join(reports_dir, report_filename)
    
    # Prepare report data
    report_data = []
    for language, stats in processing_stats.items():
        for repo_stats in stats:
            report_data.append({
                'language': language,
                'repository': repo_stats['repository'],
                'input_file': repo_stats['input_file'],
                'output_file': repo_stats['output_file'],
                'total_prs': repo_stats['total_prs'],
                'processed_prs': repo_stats['processed_prs'],
                'duplicates_filtered': repo_stats['duplicates_filtered'],
                'validation_errors': repo_stats['validation_errors'],
                'processing_time': repo_stats['processing_time'],
                'file_size_mb': repo_stats['file_size_mb'],
                'success': repo_stats['success']
            })
    
    # Write report
    write_csv_report(report_path, report_data)
    print(f"📊 Processing report generated: {report_path}")
```

### Quality Metrics
```python
def calculate_quality_metrics(processing_stats):
    """Calculate quality metrics from processing statistics."""
    total_files = sum(len(stats) for stats in processing_stats.values())
    successful_files = sum(
        sum(1 for repo in stats if repo['success']) 
        for stats in processing_stats.values()
    )
    
    total_prs = sum(
        sum(repo['total_prs'] for repo in stats)
        for stats in processing_stats.values()
    )
    
    processed_prs = sum(
        sum(repo['processed_prs'] for repo in stats)
        for stats in processing_stats.values()
    )
    
    return {
        'total_files': total_files,
        'successful_files': successful_files,
        'success_rate': successful_files / total_files if total_files > 0 else 0,
        'total_prs': total_prs,
        'processed_prs': processed_prs,
        'processing_rate': processed_prs / total_prs if total_prs > 0 else 0
    }
```

## Error Handling

### File Processing Errors
```python
def handle_file_processing_error(input_file, error):
    """Handle file processing errors gracefully."""
    error_info = {
        'file': input_file,
        'error_type': type(error).__name__,
        'error_message': str(error),
        'timestamp': datetime.now().isoformat()
    }
    
    # Log error
    log_processing_error(error_info)
    
    # Generate error report
    generate_error_report(error_info)
    
    # Return failure stats
    return {
        'repository': extract_repo_name_from_filename(input_file),
        'input_file': input_file,
        'success': False,
        'error': str(error),
        'total_prs': 0,
        'processed_prs': 0
    }
```

### Data Validation Errors
```python
def handle_validation_errors(validation_results, input_file):
    """Handle data validation errors."""
    if validation_results['invalid_records'] > 0:
        error_rate = validation_results['invalid_records'] / (
            validation_results['valid_records'] + validation_results['invalid_records']
        )
        
        if error_rate > 0.1:  # More than 10% errors
            raise ValueError(f"High error rate ({error_rate:.1%}) in {input_file}")
        
        # Log warnings for individual errors
        for error in validation_results['errors']:
            log_validation_warning(error, input_file)
```

## Performance Optimization

### Memory Management
```python
def process_large_file(input_file, output_file, chunk_size=1000):
    """Process large files in chunks to manage memory."""
    with open(input_file, 'r') as infile:
        with open(output_file, 'w', newline='') as outfile:
            writer = csv.writer(outfile)
            
            # Write header
            writer.writerow(get_csv_headers())
            
            # Process in chunks
            chunk = []
            for line in infile:
                chunk.append(json.loads(line))
                
                if len(chunk) >= chunk_size:
                    processed_chunk = process_data_chunk(chunk)
                    write_chunk_to_csv(writer, processed_chunk)
                    chunk = []
            
            # Process remaining data
            if chunk:
                processed_chunk = process_data_chunk(chunk)
                write_chunk_to_csv(writer, processed_chunk)
```

### Parallel Processing
```python
def process_files_in_parallel(file_list, max_workers=4):
    """Process multiple files in parallel."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_json_file, input_file, output_file): input_file
            for input_file, output_file in file_list
        }
        
        results = []
        for future in as_completed(futures):
            input_file = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                error_result = handle_file_processing_error(input_file, e)
                results.append(error_result)
        
        return results
```

## Integration with Workflow

### Workflow Position
1. scan_github_repos.py
2. logical_repo_checks.py
3. agentic_pr_checker_clean.py
4. update_from_LT.py
5. sheet_organizer.py
6. create_repo_batches.py
7. **convert.py** ← You are here

### Integration Points
```python
# Called after batch creation
from src.convert import process_language_directories

# Convert all generated JSON files
processing_stats = process_language_directories(
    base_dir=".",
    existing_repos=get_existing_repos_set(),
    force=False
)

# Generate processing report
create_processing_report(processing_stats, ".")
```

### Data Flow
```
JSON Files → convert.py → CSV Files + Processing Reports
```

## Best Practices

### 1. Data Quality
- Validate all input data before processing
- Handle missing or malformed data gracefully
- Generate comprehensive error reports

### 2. Performance
- Use chunked processing for large files
- Implement parallel processing when appropriate
- Monitor memory usage during conversion

### 3. Reliability
- Create backups before processing
- Implement proper error recovery
- Validate output data integrity

### 4. Maintenance
- Regular cleanup of temporary files
- Monitor processing statistics
- Update validation rules as needed

## Troubleshooting

### Common Issues

#### Memory Issues with Large Files
```python
# Use chunked processing
process_large_file(input_file, output_file, chunk_size=500)

# Monitor memory usage
import psutil
memory_usage = psutil.virtual_memory().percent
```

#### Validation Failures
```python
# Debug validation issues
validation_results = validate_json_data(pr_data)
for error in validation_results['errors']:
    print(f"Validation error: {error}")
```

#### File Permission Issues
```python
# Check file permissions
import os
if not os.access(input_file, os.R_OK):
    raise PermissionError(f"Cannot read input file: {input_file}")

if not os.access(os.path.dirname(output_file), os.W_OK):
    raise PermissionError(f"Cannot write to output directory: {output_file}")
```

## Advanced Features

### Custom Data Enrichment
```python
def add_custom_metrics(pr_data):
    """Add custom metrics to PR data."""
    # Calculate code quality score
    pr_data['code_quality_score'] = calculate_code_quality(pr_data)
    
    # Add complexity metrics
    pr_data['complexity_score'] = calculate_complexity(pr_data)
    
    # Add categorization
    pr_data['pr_category'] = categorize_pr(pr_data)
    
    return pr_data
```

### Format Converters
```python
def convert_to_excel(csv_file, excel_file):
    """Convert CSV to Excel format."""
    import pandas as pd
    
    df = pd.read_csv(csv_file)
    df.to_excel(excel_file, index=False)
```

### Data Analysis
```python
def analyze_conversion_results(processing_stats):
    """Analyze conversion results for insights."""
    analysis = {
        'languages_processed': len(processing_stats),
        'total_repositories': sum(len(stats) for stats in processing_stats.values()),
        'average_prs_per_repo': calculate_average_prs(processing_stats),
        'quality_distribution': analyze_quality_distribution(processing_stats)
    }
    
    return analysis
``` 
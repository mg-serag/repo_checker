# Logical Repository Checker

## Overview

`logical_repo_checks.py` is the core evaluation engine that assesses GitHub repositories against strict quality criteria. It performs comprehensive analysis including language detection, star validation, lines of code counting, and duplicate prevention. The script also handles automatic repository movement between language sheets based on actual majority language.

## Features

### 🎯 Multi-Criteria Evaluation
- **Language Analysis**: Detects majority language and percentage with JS/TS combination
- **Star Rating Validation**: Configurable minimum star requirements per language
- **Lines of Code Analysis**: Intelligent LOC counting with star-based thresholds
- **Duplicate Detection**: Prevents duplicate processing across sheets and labeling tool

### 🔄 Repository Movement
- **Automatic Repositioning**: Moves repositories to correct language sheets
- **Majority Language Detection**: Based on actual code analysis, not configuration
- **Data Integrity**: Preserves all repository data during movement
- **Cross-sheet Organization**: Maintains clean language-specific sheets

### 📊 Resume Capability
- **Smart Resume**: Only performs missing checks to save time
- **State Preservation**: Maintains existing evaluation results
- **Partial Completion**: Handles interrupted evaluations gracefully
- **Progress Tracking**: Shows which checks are being performed

## Configuration

### Language Settings
Configure evaluation criteria in `language_configs.json`:

```json
{
  "JavaScript": {
    "sheet_name": "JS/TS",
    "target_language": "JavaScript",
    "evaluation": {
      "min_stars": 400,
      "min_percentage": 50,
      "loc_thresholds": {
        "400": 1000,
        "1000": 2000,
        "5000": 5000,
        "10000": 10000
      }
    }
  }
}
```

### Script Configuration
```python
# Target language for evaluation
TARGET_LANGUAGE = 'JavaScript'

# Column mappings (automatically detected from headers)
COLUMN_CONFIG = {
    'user_repo': {'headers': ['repository'], 'default_index': 0},
    'majority_language': {'headers': ['majority language'], 'default_index': 3},
    'percentage': {'headers': ['%'], 'default_index': 4},
    'stars': {'headers': ['stars'], 'default_index': 5},
    'loc': {'headers': ['loc'], 'default_index': 6},
    'logical_checks': {'headers': ['logical checks'], 'default_index': 8}
}
```

## Usage

### Command Line Interface

```bash
# Basic usage
python src/logical_repo_checks.py

# The script automatically:
# 1. Fetches repositories from Google Sheets
# 2. Updates with labeling tool data
# 3. Performs missing evaluations
# 4. Moves repositories to correct sheets
# 5. Updates sheets with results
```

### Programmatic Usage

```python
from src.logical_repo_checks import evaluate_repo, evaluate_repo_with_resume

# Evaluate a single repository
result = evaluate_repo(
    user_repo="facebook/react",
    all_repos_df=df,
    column_indices=column_indices,
    existing_lt_repos=existing_repos,
    row_number=5
)

# Resume-aware evaluation (only missing checks)
result = evaluate_repo_with_resume(
    user_repo="facebook/react",
    row=sheet_row,
    all_repos_df=df,
    column_indices=column_indices,
    existing_lt_repos=existing_repos,
    row_number=5
)
```

## Evaluation Criteria

### 1. Language Analysis
```python
def combine_js_ts_languages(language_percentages):
    """Combine JavaScript and TypeScript as single language."""
    js_percent = language_percentages.get('JavaScript', 0)
    ts_percent = language_percentages.get('TypeScript', 0)
    
    if js_percent > 0 or ts_percent > 0:
        combined_percent = js_percent + ts_percent
        # Use more dominant language name
        if ts_percent > js_percent:
            language_percentages['TypeScript'] = combined_percent
        else:
            language_percentages['JavaScript'] = combined_percent
    
    return language_percentages
```

**Key Features:**
- Detects majority language from GitHub API
- Combines JavaScript and TypeScript percentages
- Always outputs majority language (not target language)
- Calculates accurate language percentages

### 2. Star Rating Validation
```python
# Language-specific star requirements
evaluation_settings = {
    'JavaScript': {'min_stars': 400},
    'Python': {'min_stars': 500},
    'Java': {'min_stars': 300}
}
```

### 3. Lines of Code Analysis
```python
def get_required_loc_for_stars(stars, loc_thresholds):
    """Get required LOC based on star count."""
    for threshold_stars, required_loc in sorted(loc_thresholds.items(), reverse=True):
        if stars >= threshold_stars:
            return required_loc
    return max(loc_thresholds.values())
```

**LOC Thresholds Example:**
- 400+ stars → 1,000 LOC minimum
- 1,000+ stars → 2,000 LOC minimum  
- 5,000+ stars → 5,000 LOC minimum
- 10,000+ stars → 10,000 LOC minimum

### 4. Duplicate Prevention
```python
def preprocess_duplicates(df, column_indices, existing_lt_repos):
    """Mark duplicates within sheet and against labeling tool."""
    # Check for URL duplicates within sheet
    duplicate_mask = normalized_urls.duplicated(keep='first')
    
    # Check against labeling tool
    for user_repo in df['user_repo']:
        if user_repo.lower() in existing_lt_repos:
            mark_as_duplicate(user_repo)
```

## Resume Logic

### Missing Check Detection
```python
def determine_missing_checks(row, column_indices):
    """Determine which checks are missing based on existing data."""
    checks_needed = {
        'language_check': is_empty(row['majority_language']),
        'stars_check': is_empty(row['stars']),
        'loc_check': is_empty(row['loc']),
        'logical_check': is_empty(row['logical_checks'])
    }
    return checks_needed
```

### Selective Evaluation
The script performs only missing checks:
- **Language Check**: If majority language or percentage is missing
- **Stars Check**: If star count is missing
- **LOC Check**: If lines of code is missing
- **Logical Check**: If final evaluation is missing

## Repository Movement

### Automatic Movement Logic
```python
def handle_repo_movement(user_repo, majority_language, current_sheet):
    """Handle repository movement based on majority language."""
    target_sheet = get_destination_sheet_for_language(majority_language)
    
    if target_sheet != current_sheet:
        # Move repository to correct sheet
        moved = process_single_repo_movement(
            client, spreadsheet, current_sheet, user_repo, majority_language
        )
        return moved
    
    return False
```

### Movement Examples
- Python repo in Java sheet → Move to Python sheet
- JavaScript repo in Java sheet → Move to JS/TS sheet
- Java repo in JS/TS sheet → Move to Java sheet

## Output Format

### Evaluation Results
```python
results = {
    'repo': 'facebook/react',
    'should_add': True,
    'reason': 'Passed criteria for JavaScript',
    'language_name': 'JavaScript',
    'language_percent': 0.94,  # 94%
    'star_count': 218542,
    'loc_count': 125000,
    'already_exists': 'No',
    'manual_review': False
}
```

### Console Output
```
=== Starting evaluation for facebook/react (Row 5) at 14:30:25 ===
[Config] Target Language: JavaScript, Min Stars: 400, Min Percentage: 50%

[Repo Info] Starting repo details fetch for facebook/react...
[Repo Info] Completed in 0.85 seconds

[LOC Check] Starting LOC check for facebook/react...
[LOC Check] Completed in 2.34 seconds

✔ ADD:       facebook/react (Row 5) - Passed criteria for JavaScript
🔄 MOVED:    vue/vue (Row 6) - Moved to JS/TS sheet

=== Evaluation completed in 3.45 seconds ===
```

### Sheet Updates
The script updates multiple columns:
- **Column D**: Majority Language (e.g., "JavaScript")
- **Column E**: Language Percentage (e.g., 0.94)
- **Column F**: Star Count (e.g., 218542)
- **Column G**: LOC Count (e.g., 125000)
- **Column H**: Already Exists (Yes/No)
- **Column I**: Logical Checks (Yes/No/Manual)

## Error Handling

### LOC Check Errors
```python
# Handle LOC API failures
if lines is None:
    results['loc_count'] = "ERROR"
    results['manual_review'] = True
elif lines == 0:
    results['loc_count'] = "ERROR 0"
    results['manual_review'] = True
```

### API Rate Limiting
```python
def make_github_api_request(url):
    """GitHub API request with rate limit handling."""
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403 and 'rate limit exceeded' in e.response.text.lower():
            reset_time = int(e.response.headers.get('X-RateLimit-Reset', time.time() + 3600))
            wait_time = max(reset_time - time.time(), 0) + 5
            time.sleep(wait_time)
            return make_github_api_request(url)  # Retry once
```

### Manual Review Triggers
Repositories require manual review when:
- LOC API returns errors
- Repository access is restricted
- Unusual language combinations detected
- API responses are inconsistent

## Performance Optimization

### Caching
```python
LOC_CACHE = {}  # Cache LOC results to avoid repeated API calls

def get_lines_count(user_repo):
    """Get LOC with caching."""
    if user_repo in LOC_CACHE:
        return LOC_CACHE[user_repo]
    
    result = fetch_loc_from_api(user_repo)
    LOC_CACHE[user_repo] = result
    return result
```

### API Efficiency
- **Sequential API Calls**: Prevents overwhelming external APIs
- **Timeout Handling**: 10-minute timeout for LOC API calls
- **Retry Logic**: Automatic retry with different branches
- **Fallback Strategies**: Multiple approaches for LOC counting

## Labeling Tool Integration

### Data Synchronization
```python
def update_data_from_LT(json_path, spreadsheet_key, scope, sheet_name, column_indices):
    """Update sheet with labeling tool data."""
    batch_data = fetch_all_batches_from_lt()
    
    for repo_name, batch_info in batch_data.items():
        # Update columns O, P, Q, R, S with labeling tool data
        update_lt_columns(repo_name, batch_info)
```

### Updated Columns
- **Column O**: Added (Yes/No)
- **Column P**: Tasks Count in LT
- **Column Q**: Improper in LT
- **Column R**: Batch Link
- **Column S**: Addition Date

## Workflow Integration

### Complete Workflow
```python
def main():
    """Main evaluation workflow."""
    # 1. Display configuration
    print_column_configuration()
    
    # 2. Fetch existing repos from labeling tool
    existing_lt_repos = fetch_existing_repos_from_lt()
    
    # 3. Fetch repository list from sheets
    potential_repos_df, header = fetch_sheet_data(CREDS_JSON_PATH, SPREADSHEET_KEY, SCOPE, SHEET_NAME)
    
    # 4. Update with labeling tool data
    update_data_from_LT(CREDS_JSON_PATH, SPREADSHEET_KEY, SCOPE, SHEET_NAME, column_indices)
    
    # 5. Preprocess duplicates
    potential_repos_df = preprocess_duplicates(potential_repos_df, column_indices, existing_lt_repos)
    
    # 6. Evaluate unprocessed repositories
    for index, row in unprocessed_rows:
        result = evaluate_repo_with_resume(user_repo, row, potential_repos_df, column_indices, existing_lt_repos, row_number)
        
        # Handle repository movement
        if result['language_name'] != "N/A":
            handle_repo_movement(user_repo, result['language_name'], SHEET_NAME)
        
        # Update sheet with results
        update_sheet_with_results(CREDS_JSON_PATH, SPREADSHEET_KEY, SCOPE, SHEET_NAME, repo_url, result, column_indices)
```

## Configuration Examples

### High-Quality Repositories
```python
EVALUATION_CONFIG = {
    'min_stars': 1000,
    'min_percentage': 70,
    'loc_thresholds': {
        '1000': 5000,
        '5000': 10000,
        '10000': 20000
    }
}
```

### Popular Repositories
```python
EVALUATION_CONFIG = {
    'min_stars': 100,
    'min_percentage': 40,
    'loc_thresholds': {
        '100': 500,
        '500': 1000,
        '1000': 2000
    }
}
```

## Troubleshooting

### Common Issues

#### Empty Sheet Results
```python
# Check sheet configuration
SPREADSHEET_KEY = '1XMbstebCi1xFSwJ7cTN-DXv4jFmdH2owWBE3R7YsXK0'
SHEET_NAME = 'JS/TS'  # Verify sheet name exists
```

#### Column Mapping Issues
```python
# Check column headers
def get_column_indices(header):
    """Map column headers to indices."""
    # Automatically detects columns by header names
    # Falls back to default indices if headers not found
```

#### LOC API Timeouts
```python
# Increase timeout for LOC API
timeout = 600  # 10 minutes
response = requests.get(url, timeout=timeout)
```

### Debug Mode
```python
# Enable detailed logging
DEBUG_MODE = True

# Check specific repository
DEBUG_REPO = "facebook/react"
```

## Best Practices

### 1. Regular Monitoring
- Check for manual review repositories
- Monitor LOC API success rates
- Verify repository movement accuracy

### 2. Configuration Management
- Regular review of star thresholds
- Adjust LOC requirements based on language
- Update language configurations as needed

### 3. Data Quality
- Validate majority language detection
- Check for duplicate repositories
- Monitor evaluation accuracy

### 4. Performance Optimization
- Use resume functionality for interrupted runs
- Monitor API rate limit usage
- Cache frequently accessed data

## Integration with Other Scripts

### Workflow Position
1. scan_github_repos.py
2. **logical_repo_checks.py** ← You are here
3. agentic_pr_checker_clean.py
4. update_from_LT.py

### Data Flow
```
Google Sheets → logical_repo_checks.py → Updated Sheets → agentic_pr_checker_clean.py
              ↓
         Repository Movement
              ↓
      Language-specific Sheets
```

## Advanced Features

### JavaScript/TypeScript Combination
```python
# Special handling for JS/TS combination
if js_percent > 0 or ts_percent > 0:
    combined_percent = js_percent + ts_percent
    # Use more dominant language name
    if ts_percent > js_percent:
        language_name = 'TypeScript'
    else:
        language_name = 'JavaScript'
```

### Multi-language Evaluation
```python
# Evaluate against both primary and target languages
primary_lang_checks_passed = all([
    language_meets_threshold(primary_lang_percent, primary_lang_settings),
    stars_meet_threshold(stars, primary_lang_settings),
    loc_meets_threshold(loc, primary_lang_settings)
])

target_lang_checks_passed = all([
    language_meets_threshold(target_lang_percent, target_lang_settings),
    stars_meet_threshold(stars, target_lang_settings),
    loc_meets_threshold(loc, target_lang_settings)
])

# Repository passes if it meets either language criteria
should_add = primary_lang_checks_passed or target_lang_checks_passed
``` 
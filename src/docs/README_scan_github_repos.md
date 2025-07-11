# GitHub Repository Scanner

## Overview

`scan_github_repos.py` is a comprehensive tool for discovering and collecting high-quality GitHub repositories based on specific criteria. It integrates with Google Sheets to maintain a centralized repository database and includes sophisticated filtering, deduplication, and batch processing capabilities.

## Features

### 🔍 Repository Discovery
- **GitHub API Integration**: Uses official GitHub API with proper rate limiting
- **Multi-language Support**: Configurable language targeting via centralized config
- **Quality Filtering**: Minimum star requirements, toolchain validation
- **Batch Processing**: Writes results in batches to prevent data loss

### 📊 Sheet Integration
- **Google Sheets API**: Direct integration with spreadsheet coordination system
- **Duplicate Prevention**: Checks existing repositories to avoid duplicates
- **Cross-sheet Analysis**: Examines other language sheets for repositioning
- **Real-time Updates**: Writes repositories immediately upon discovery

### 🔄 Advanced Features
- **Resume Capability**: Can resume from interruptions using skip functionality
- **Rate Limit Handling**: Automatic rate limit detection and waiting
- **Parallel Processing**: Efficient API usage with request batching
- **Language-specific Toolchains**: Validates appropriate build systems

## Configuration

### Language Settings
Configure target languages in `language_configs.json`:

```json
{
  "JavaScript": {
    "sheet_name": "JS/TS",
    "github_language": "javascript",
    "dependency_files": ["package.json", "yarn.lock", "npm-shrinkwrap.json"],
    "source_extensions": [".js", ".jsx", ".mjs", ".cjs"]
  }
}
```

### Script Parameters
```python
# Repository Discovery Configuration
MIN_STARS = 400              # Minimum stars for repositories
PULL_REPO_COUNT = 10000      # Number of new repos to fetch per run
SKIP_FIRST_RESULTS = 0       # Skip N results (for resuming)
CHECK_OTHER_SHEETS = True    # Check other language sheets
TARGET_LANGUAGE = "JavaScript"  # Target language for scanning
```

## Usage

### Command Line Interface

```bash
# Basic usage
python src/scan_github_repos.py

# With custom parameters
python src/scan_github_repos.py --language JavaScript --count 5000 --min-stars 500

# Resume from interruption
python src/scan_github_repos.py --skip 2000 --count 3000

# Disable cross-sheet checking
python src/scan_github_repos.py --no-check-other-sheets
```

### Available Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--language` | Target language | JavaScript |
| `--count` | Number of repositories to fetch | 10000 |
| `--min-stars` | Minimum stars required | 400 |
| `--skip` | Number of results to skip | 0 |
| `--check-other-sheets` | Check other language sheets | True |
| `--no-check-other-sheets` | Disable cross-sheet checking | False |

### Programmatic Usage

```python
from src.scan_github_repos import search_github_repos, authenticate_google_sheets

# Setup clients
gsheet_client = authenticate_google_sheets()
gh_client = get_github_client()

# Get existing repositories
existing_repos, _ = get_existing_repositories(gsheet_client, "JS/TS")

# Search for new repositories
new_repos = search_github_repos(
    gh_client, 
    existing_repos, 
    max_needed=1000,
    language="JavaScript",
    gsheet_client=gsheet_client,
    sheet_name="JS/TS"
)
```

## Workflow Integration

### 1. Pre-execution Setup
```python
# Authenticate with Google Sheets
gsheet_client = authenticate_google_sheets()

# Authenticate with GitHub
gh_client = get_github_client()

# Load language configuration
sheet_name = get_sheet_name_for_language(TARGET_LANGUAGE)
```

### 2. Repository Discovery
```python
# Get existing repositories for duplicate checking
existing_repos, current_count = get_existing_repositories(gsheet_client, sheet_name)

# Search for new repositories
repo_df = search_github_repos(
    gh_client,
    existing_repos,
    max_needed=PULL_REPO_COUNT,
    language=TARGET_LANGUAGE,
    gsheet_client=gsheet_client,
    sheet_name=sheet_name,
    skip_first=SKIP_FIRST_RESULTS
)
```

### 3. Cross-sheet Analysis
```python
# Check other language sheets for repositioning
check_other_language_sheets(gsheet_client, TARGET_LANGUAGE, sheet_name)
```

## Quality Filters

### Repository Criteria
1. **Star Count**: Minimum star requirement (configurable)
2. **Modern Toolchain**: Must contain appropriate build/dependency files
3. **Active Development**: Recent activity and commits
4. **Language Dominance**: Primary language must match target

### Toolchain Validation
The script validates repositories have appropriate toolchains:

```python
def has_modern_toolchain(repo, language, cache):
    """Check if repository has appropriate build/dependency files."""
    dependency_files = get_dependency_files(language)
    
    for file_pattern in dependency_files:
        try:
            repo.get_contents(file_pattern)
            return True
        except GithubException:
            continue
    
    return False
```

## Batch Processing

### Batch Size Configuration
```python
batch_size = 100  # Write to sheet every 100 repositories
```

### Batch Processing Flow
1. **Collection Phase**: Accumulate repositories in memory
2. **Batch Write**: Write 100 repositories to sheet
3. **Progress Tracking**: Real-time progress updates
4. **Error Recovery**: Continue processing if individual repos fail

## Output Format

### Google Sheets Structure
| Column | Header | Purpose |
|--------|--------|---------|
| A | Repository | USER/REPO format |
| B | Empty | Reserved |
| C | URL | Full GitHub URL |

### Console Output
```
=== Searching for JavaScript repositories ===
GitHub query: language:javascript stars:>400 sort:stars-desc
Toolchain requirement: Project with package.json, yarn.lock, etc.

--- Checking repository: facebook/react (⭐ 218542) ---
  [Pass] Repository is eligible. Adding to list...
  [Success] Added facebook/react. Total found: 1/1000

=== Writing batch of 100 repositories to sheet ===
=== Batch written successfully ===
```

## Error Handling

### Rate Limit Management
```python
def make_github_api_request(url, params=None):
    """Make GitHub API request with rate limit handling."""
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403 and 'rate limit exceeded' in e.response.text.lower():
            reset_time = int(e.response.headers.get('X-RateLimit-Reset', time.time() + 3600))
            wait_time = max(reset_time - time.time(), 0) + 5
            time.sleep(wait_time)
            return make_github_api_request(url, params)
```

### Common Error Scenarios
1. **Rate Limit Exceeded**: Automatic waiting and retry
2. **Network Timeouts**: Exponential backoff retry
3. **Sheet Access Errors**: Credential validation and re-authentication
4. **API Authentication**: Token validation and refresh

## Performance Optimization

### API Efficiency
- **Batch Requests**: Group API calls when possible
- **Caching**: Cache toolchain validation results
- **Pagination**: Efficient pagination handling
- **Request Timing**: Intelligent request spacing

### Memory Management
- **Streaming Processing**: Process repositories as they're discovered
- **Batch Writing**: Prevent memory buildup with large result sets
- **Resource Cleanup**: Proper cleanup of API connections

## Resume Functionality

### How Resume Works
1. **Skip Parameter**: Use `--skip N` to skip first N results
2. **State Preservation**: Existing sheet data is preserved
3. **Duplicate Prevention**: Continues to check for duplicates
4. **Progress Tracking**: Shows adjusted progress counting

### Resume Example
```bash
# Initial run (interrupted after 2000 repos)
python src/scan_github_repos.py --count 5000

# Resume from where it left off
python src/scan_github_repos.py --skip 2000 --count 3000
```

## Monitoring and Logging

### Progress Tracking
```
Target sheet: JS/TS
Minimum stars: 400
Existing repositories to avoid: 1,247
Batch size for writing: 100

--- Checking repository: facebook/react (⭐ 218542) ---
  [Pass] Repository is eligible. Adding to list...
  [Success] Added facebook/react. Total found: 1/1000
```

### Summary Statistics
```
=== Repository Discovery Summary ===
Languages searched: ['JavaScript']
New repositories found: 1000
Duplicates skipped: 47
Toolchain requirement failures: 153
Total repositories processed: 1200
```

## Integration with Other Scripts

### Workflow Position
1. **scan_github_repos.py** ← You are here
2. logical_repo_checks.py
3. agentic_pr_checker_clean.py
4. update_from_LT.py

### Data Flow
```
GitHub API → scan_github_repos.py → Google Sheets → logical_repo_checks.py
```

## Troubleshooting

### Common Issues

#### Authentication Problems
```bash
# Check GitHub token
export GITHUB_TOKEN="your_token_here"

# Verify Google Sheets credentials
ls -la src/creds.json
```

#### Sheet Access Issues
```python
# Verify sheet ID and permissions
SHEET_ID = '1XMbstebCi1xFSwJ7cTN-DXv4jFmdH2owWBE3R7YsXK0'
```

#### Rate Limiting
```
⏳ Rate limit exceeded. Waiting for 3600 seconds until reset...
```
- **Solution**: Wait for rate limit reset or use multiple tokens

### Debug Mode
```python
# Enable debug output
DEBUG_MODE = True

# Check specific repository
DEBUG_REPO = "facebook/react"
```

## Best Practices

### 1. Regular Monitoring
- Monitor rate limit usage
- Check for failed repositories
- Verify sheet updates are working

### 2. Batch Size Optimization
- Use smaller batches for unstable networks
- Increase batch size for faster processing
- Monitor memory usage with large batches

### 3. Resume Strategy
- Note progress before interruptions
- Use skip parameter for precise resumption
- Verify duplicate prevention is working

### 4. Quality Assurance
- Regularly review discovered repositories
- Check toolchain validation accuracy
- Monitor false positive rates

## Configuration Examples

### High-Volume Processing
```python
MIN_STARS = 100
PULL_REPO_COUNT = 50000
SKIP_FIRST_RESULTS = 0
CHECK_OTHER_SHEETS = True
```

### Conservative Processing
```python
MIN_STARS = 1000
PULL_REPO_COUNT = 1000
SKIP_FIRST_RESULTS = 0
CHECK_OTHER_SHEETS = False
```

### Resume Processing
```python
MIN_STARS = 400
PULL_REPO_COUNT = 10000
SKIP_FIRST_RESULTS = 5000  # Resume from 5000
CHECK_OTHER_SHEETS = True
``` 
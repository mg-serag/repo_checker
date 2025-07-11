# Labeling Tool Data Synchronization

## Overview

`update_from_LT.py` synchronizes data between Google Sheets and the Labeling Tool (LT) platform. It fetches batch information, task statistics, and repository status from the LT API and updates the corresponding Google Sheets with real-time data about repository processing status, task counts, and quality metrics.

## Features

### 🔄 Bi-directional Sync
- **LT to Sheets**: Updates sheets with latest LT data
- **Status Tracking**: Monitors repository processing status
- **Task Metrics**: Fetches task counts and quality statistics
- **Batch Links**: Maintains links to LT batches for easy access

### 📊 Multi-language Support
- **Language-specific Projects**: Handles different project IDs per language
- **Batch Organization**: Organizes batches by language and project
- **Cross-language Compatibility**: Supports all configured languages
- **Project Management**: Manages multiple LT projects simultaneously

### 🔍 Smart Updates
- **Differential Updates**: Only updates changed data
- **Batch Processing**: Efficient bulk updates
- **Error Handling**: Robust error handling and retry logic
- **Rate Limiting**: Respects API rate limits

## Configuration

### Project IDs by Language
Configure in `language_configs.json`:
```json
{
  "JavaScript": {
    "project_id": 41,
    "sheet_name": "JS/TS"
  },
  "Python": {
    "project_id": 42,
    "sheet_name": "Python"
  },
  "Java": {
    "project_id": 43,
    "sheet_name": "Java"
  }
}
```

### API Configuration
```python
# Labeling Tool API settings
LT_BASE_URL = "https://eval.turing.com/api"
LT_TOKEN = get_lt_token()  # From config or environment

# Batch API configuration
BATCH_LIMIT = 100  # Number of batches per API call
MAX_RETRIES = 3    # Maximum retry attempts
TIMEOUT = 30       # Request timeout in seconds
```

## Usage

### Command Line Interface

```bash
# Update all language sheets
python src/update_from_LT.py

# Update specific language
python src/update_from_LT.py --language JavaScript

# Update specific sheet
python src/update_from_LT.py --sheet "JS/TS"

# Dry run (preview changes)
python src/update_from_LT.py --dry-run

# Verbose output
python src/update_from_LT.py --verbose
```

### Available Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--language` | Target language to update | All languages |
| `--sheet` | Specific sheet name to update | All sheets |
| `--dry-run` | Preview changes without applying | False |
| `--verbose` | Detailed output | False |
| `--force` | Force update even if no changes | False |

### Programmatic Usage

```python
from src.update_from_LT import update_sheet_from_LT, fetch_all_batches_from_lt

# Update specific sheet
update_sheet_from_LT(
    json_path="src/creds.json",
    spreadsheet_key="1XMbstebCi1xFSwJ7cTN-DXv4jFmdH2owWBE3R7YsXK0",
    scope=['https://spreadsheets.google.com/feeds'],
    sheet_name="JS/TS",
    column_indices=column_indices,
    project_id=41
)

# Fetch batch data
batch_data = fetch_all_batches_from_lt(project_id=41)
```

## Data Synchronization

### Batch Data Structure
```python
{
    "id": 12345,
    "name": "facebook__react",
    "status": "completed",
    "countOfConversations": 847,
    "createdAt": "2024-01-15T10:30:00Z",
    "batchStats": {
        "proper": 623,
        "improper": 224,
        "total": 847
    }
}
```

### Sheet Updates
Updates the following columns:

| Column | Header | Data Source | Description |
|--------|--------|-------------|-------------|
| O | Added | Batch existence | Yes/No based on LT presence |
| P | Tasks Count in LT | countOfConversations | Total task count |
| Q | Improper in LT | batchStats.improper | Improper task count |
| R | Batch Link | Generated URL | Direct link to LT batch |
| S | Addition Date | createdAt | Date added to LT |

## Update Logic

### Repository Name Conversion
```python
def convert_repo_name_to_lt_format(repo_name):
    """Convert USER/REPO to USER__REPO format."""
    return repo_name.replace('/', '__')

def convert_lt_name_to_repo_format(lt_name):
    """Convert USER__REPO to USER/REPO format."""
    return lt_name.replace('__', '/')
```

### Smart Update Rules
1. **New Repositories**: Mark as "Yes" and populate all LT columns
2. **Existing Repositories**: Refresh counts and metrics only
3. **Missing Repositories**: Mark as "No" and clear LT columns
4. **Already Processed**: Skip to avoid unnecessary updates

### Batch Processing
```python
def process_batch_updates(sheet, batch_data, column_indices):
    """Process batch updates efficiently."""
    cell_updates = []
    
    for repo_name, batch_info in batch_data.items():
        # Convert LT format to sheet format
        sheet_repo_name = convert_lt_name_to_repo_format(repo_name)
        
        # Find corresponding sheet row
        row_index = find_repo_row(sheet, sheet_repo_name)
        
        if row_index:
            # Prepare batch update
            cell_updates.extend(prepare_cell_updates(row_index, batch_info, column_indices))
    
    # Batch update all cells
    if cell_updates:
        sheet.update_cells(cell_updates, value_input_option='USER_ENTERED')
```

## API Integration

### Authentication
```python
def get_lt_headers():
    """Get authenticated headers for LT API."""
    return {
        "Authorization": f"Bearer {LT_TOKEN}",
        "Content-Type": "application/json"
    }
```

### Batch Fetching
```python
def fetch_all_batches_from_lt(project_id):
    """Fetch all batches for a project with pagination."""
    base_url = f"{LT_BASE_URL}/batches"
    params = {
        "sort[0]": "createdAt,DESC",
        "join[0]": "batchStats",
        "join[1]": "importAttempts",
        "filter[0]": f"projectId||$eq||{project_id}",
        "limit": BATCH_LIMIT
    }
    
    all_batches = []
    page = 1
    
    while True:
        params["page"] = page
        response = requests.get(base_url, headers=get_lt_headers(), params=params)
        
        if response.status_code != 200:
            break
            
        data = response.json()
        batches = data.get("data", [])
        
        if not batches:
            break
            
        all_batches.extend(batches)
        
        if len(batches) < BATCH_LIMIT:
            break
            
        page += 1
    
    return organize_batches_by_name(all_batches)
```

### Error Handling
```python
def make_lt_api_request(url, params=None, retries=MAX_RETRIES):
    """Make LT API request with retry logic."""
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=get_lt_headers(), params=params, timeout=TIMEOUT)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
                continue
            else:
                raise e
```

## Multi-language Processing

### Language Detection
```python
def get_sheets_to_update():
    """Get all language sheets that need updating."""
    try:
        all_languages = get_all_language_configs()
        sheets_to_update = []
        
        for lang_name, config in all_languages.items():
            if config.get('project_id') and config.get('sheet_name'):
                sheets_to_update.append({
                    'language': lang_name,
                    'sheet_name': config['sheet_name'],
                    'project_id': config['project_id']
                })
        
        return sheets_to_update
    except Exception as e:
        print(f"Error loading language configs: {e}")
        return []
```

### Batch Processing by Language
```python
def update_all_language_sheets():
    """Update all language sheets with LT data."""
    sheets_to_update = get_sheets_to_update()
    
    for sheet_info in sheets_to_update:
        print(f"Updating {sheet_info['language']} ({sheet_info['sheet_name']})...")
        
        try:
            update_sheet_from_LT(
                json_path=CREDS_JSON_PATH,
                spreadsheet_key=SPREADSHEET_KEY,
                scope=SCOPE,
                sheet_name=sheet_info['sheet_name'],
                column_indices=get_column_indices(sheet_info['sheet_name']),
                project_id=sheet_info['project_id']
            )
            print(f"✅ Updated {sheet_info['language']} successfully")
        except Exception as e:
            print(f"❌ Failed to update {sheet_info['language']}: {e}")
```

## Output Format

### Console Output
```
=== Starting Labeling Tool Data Update ===

Updating JavaScript (JS/TS)...
[Labeling Tool] Fetching batch data for JavaScript project (ID: 41)...
[Labeling Tool] Found 1,247 batches with valid names

Processing 2,156 data rows...
  Updated row 5: Found facebook/react in LT.
  Refreshed counts for existing repo in row 12: microsoft/vscode
  Updated row 23: Found vue/vue in LT.

✅ Successfully updated sheet: marked 67 new repos as added and refreshed counts for 234 existing repos.

Updating Python...
[Labeling Tool] Fetching batch data for Python project (ID: 42)...
[Labeling Tool] Found 892 batches with valid names

✅ Updated Python successfully

📊 Summary:
   Languages processed: 3
   Repositories updated: 1,423
   New repositories found: 123
   Existing repositories refreshed: 1,300
   Processing time: 45.2 seconds
```

### Sheet Updates
Before update:
| Repository | Added | Tasks Count | Improper | Batch Link | Addition Date |
|------------|-------|-------------|----------|------------|---------------|
| facebook/react | | | | | |
| microsoft/vscode | Yes | 892 | 67 | https://... | 2024-01-15 |

After update:
| Repository | Added | Tasks Count | Improper | Batch Link | Addition Date |
|------------|-------|-------------|----------|------------|---------------|
| facebook/react | Yes | 1,247 | 89 | https://eval.turing.com/batches/12345/view | 2024-01-20 |
| microsoft/vscode | Yes | 934 | 71 | https://eval.turing.com/batches/12346/view | 2024-01-15 |

## Performance Optimization

### Batch API Calls
```python
def optimize_api_calls():
    """Strategies for efficient API usage."""
    # 1. Use pagination efficiently
    # 2. Implement proper caching
    # 3. Minimize redundant requests
    # 4. Use batch updates for sheets
```

### Caching Strategy
```python
CACHE_DURATION = 300  # 5 minutes

@lru_cache(maxsize=128)
def get_cached_batch_data(project_id):
    """Cache batch data to reduce API calls."""
    return fetch_all_batches_from_lt(project_id)
```

### Memory Management
```python
def process_in_chunks(data, chunk_size=100):
    """Process data in chunks to manage memory."""
    for i in range(0, len(data), chunk_size):
        yield data[i:i + chunk_size]
```

## Error Handling

### Common Errors
```python
def handle_api_errors(response):
    """Handle common LT API errors."""
    if response.status_code == 401:
        raise AuthenticationError("Invalid LT token")
    elif response.status_code == 429:
        raise RateLimitError("API rate limit exceeded")
    elif response.status_code == 404:
        raise NotFoundError("Project or batch not found")
    else:
        response.raise_for_status()
```

### Retry Logic
```python
def retry_on_failure(func, max_retries=3, delay=1):
    """Retry function on failure with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(delay * (2 ** attempt))
                continue
            else:
                raise e
```

## Integration with Workflow

### Workflow Position
1. scan_github_repos.py
2. logical_repo_checks.py
3. agentic_pr_checker_clean.py
4. **update_from_LT.py** ← You are here
5. sheet_organizer.py
6. create_repo_batches.py

### Data Flow
```
Labeling Tool API → update_from_LT.py → Google Sheets → Other Scripts
```

### Integration Points
```python
# Called by logical_repo_checks.py
from update_from_LT import update_data_from_LT

# Update LT data before evaluation
update_data_from_LT(
    json_path=CREDS_JSON_PATH,
    spreadsheet_key=SPREADSHEET_KEY,
    scope=SCOPE,
    sheet_name=SHEET_NAME,
    column_indices=column_indices
)
```

## Monitoring and Logging

### Metrics Tracking
```python
def track_update_metrics():
    """Track update performance metrics."""
    return {
        'total_repositories': len(all_repos),
        'updated_repositories': len(updated_repos),
        'new_repositories': len(new_repos),
        'api_calls_made': api_call_count,
        'processing_time': end_time - start_time,
        'success_rate': success_count / total_count
    }
```

### Logging Configuration
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('lt_sync.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)
```

## Best Practices

### 1. Regular Synchronization
- Run updates at regular intervals
- Monitor for failed updates
- Verify data consistency

### 2. Error Recovery
- Implement proper retry logic
- Handle network failures gracefully
- Maintain update logs

### 3. Performance Monitoring
- Track API usage and limits
- Monitor update performance
- Optimize batch sizes

### 4. Data Validation
- Verify repository name formats
- Check for missing project IDs
- Validate batch data integrity

## Troubleshooting

### Common Issues

#### Authentication Failures
```python
# Check LT token validity
if not LT_TOKEN:
    raise ValueError("LT_TOKEN not configured")

# Verify token permissions
response = requests.get(f"{LT_BASE_URL}/profile", headers=get_lt_headers())
if response.status_code != 200:
    raise AuthenticationError("Invalid LT token or insufficient permissions")
```

#### Project ID Issues
```python
# Verify project ID exists
def validate_project_id(project_id):
    """Validate project ID exists in LT."""
    response = requests.get(f"{LT_BASE_URL}/projects/{project_id}", headers=get_lt_headers())
    return response.status_code == 200
```

#### Sheet Access Problems
```python
# Check sheet permissions
def verify_sheet_access(spreadsheet_key, sheet_name):
    """Verify sheet access and permissions."""
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)
        return True
    except Exception as e:
        print(f"Sheet access error: {e}")
        return False
```

## Advanced Features

### Selective Updates
```python
def update_only_new_repos():
    """Update only repositories not yet in LT."""
    # Filter repositories that don't have "Added" = "Yes"
    # Update only those repositories
```

### Data Validation
```python
def validate_batch_data(batch_data):
    """Validate batch data before updating sheets."""
    required_fields = ['id', 'name', 'countOfConversations', 'createdAt']
    
    for batch in batch_data:
        for field in required_fields:
            if field not in batch:
                raise ValueError(f"Missing required field: {field}")
```

### Custom Metrics
```python
def calculate_quality_metrics(batch_data):
    """Calculate quality metrics from batch data."""
    total_tasks = sum(batch.get('countOfConversations', 0) for batch in batch_data)
    total_improper = sum(batch.get('batchStats', {}).get('improper', 0) for batch in batch_data)
    
    return {
        'total_tasks': total_tasks,
        'total_improper': total_improper,
        'quality_ratio': (total_tasks - total_improper) / total_tasks if total_tasks > 0 else 0
    }
``` 
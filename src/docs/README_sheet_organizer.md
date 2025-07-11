# Sheet Organizer & Repository Management

## Overview

`sheet_organizer.py` automatically organizes repositories across language-specific Google Sheets based on their detected majority language. It handles repository movement, duplicate removal, and data integrity maintenance across multiple sheets, ensuring that repositories are properly categorized and organized.

## Features

### 🔄 Automatic Repository Movement
- **Language-based Organization**: Moves repositories to correct language sheets
- **Majority Language Detection**: Based on actual code analysis, not configuration
- **Data Preservation**: Maintains all repository data during movement
- **Cross-sheet Coordination**: Handles complex multi-sheet operations

### 🧹 Duplicate Management
- **Intra-sheet Deduplication**: Removes duplicates within individual sheets
- **Cross-sheet Deduplication**: Prevents duplicates across different language sheets
- **Smart Merging**: Combines data from duplicate entries intelligently
- **Preservation Logic**: Keeps the most complete data record

### 🔒 Data Integrity
- **Atomic Operations**: Ensures complete success or rollback
- **Validation Checks**: Validates data before and after operations
- **Backup Mechanisms**: Creates backups before major operations
- **Error Recovery**: Handles partial failures gracefully

## Configuration

### Language Sheet Mapping
Configure in `language_configs.json`:
```json
{
  "JavaScript": {
    "sheet_name": "JS/TS",
    "target_language": "JavaScript"
  },
  "TypeScript": {
    "sheet_name": "JS/TS",
    "target_language": "TypeScript"
  },
  "Python": {
    "sheet_name": "Python",
    "target_language": "Python"
  }
}
```

### Sheet Organization Rules
```python
# Default destination mapping
SHEET_MAPPING = {
    'JavaScript': 'JS/TS',
    'TypeScript': 'JS/TS',
    'Python': 'Python',
    'Java': 'Java',
    'Go': 'Go',
    'C': 'C/C++',
    'C++': 'C/C++',
    'Rust': 'Rust',
    'C#': 'C#',
    'Ruby': 'Ruby'
}
```

## Usage

### Command Line Interface

```bash
# Organize all sheets
python src/sheet_organizer.py

# Organize specific sheet
python src/sheet_organizer.py --sheet "JS/TS"

# Remove duplicates only
python src/sheet_organizer.py --remove-duplicates

# Dry run (preview changes)
python src/sheet_organizer.py --dry-run

# Verbose output
python src/sheet_organizer.py --verbose
```

### Available Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--sheet` | Specific sheet to organize | All sheets |
| `--remove-duplicates` | Only remove duplicates | False |
| `--dry-run` | Preview changes without applying | False |
| `--verbose` | Detailed output | False |
| `--backup` | Create backup before changes | True |

### Programmatic Usage

```python
from src.sheet_organizer import organize_sheets, remove_duplicates_within_sheet

# Organize all sheets
organize_sheets()

# Remove duplicates in specific sheet
remove_duplicates_within_sheet(client, spreadsheet, "JS/TS")

# Process single repository movement
moved = process_single_repo_movement(
    client, spreadsheet, "Java", "facebook/react", "JavaScript"
)
```

## Repository Movement Logic

### Decision Process
```python
def get_destination_sheet_for_language(language):
    """Determine target sheet for a given language."""
    try:
        config = get_language_config(language)
        return config.get('sheet_name', language)
    except (KeyError, FileNotFoundError):
        # Fallback to default mapping
        return SHEET_MAPPING.get(language, language)
```

### Movement Workflow
1. **Detection**: Identify repositories with mismatched languages
2. **Validation**: Verify target sheet exists and is accessible
3. **Preparation**: Prepare repository data for movement
4. **Execution**: Move repository to target sheet
5. **Cleanup**: Remove original entry and update references
6. **Verification**: Confirm successful movement

### Movement Examples
```python
# Python repository in Java sheet
Source: Java sheet, Row 45, "scikit-learn/scikit-learn" (Python 95%)
Target: Python sheet, New row, Complete data transfer

# JavaScript repository in Python sheet  
Source: Python sheet, Row 123, "facebook/react" (JavaScript 94%)
Target: JS/TS sheet, New row, Complete data transfer
```

## Duplicate Management

### Duplicate Detection
```python
def find_duplicates_in_sheet(sheet_data):
    """Find duplicate repositories within a sheet."""
    seen_repos = set()
    duplicates = []
    
    for index, row in sheet_data.iterrows():
        repo_name = row['repository'].strip().lower()
        if repo_name in seen_repos:
            duplicates.append((index, repo_name))
        else:
            seen_repos.add(repo_name)
    
    return duplicates
```

### Duplicate Resolution
```python
def resolve_duplicate_entries(entries):
    """Resolve duplicate entries by merging data."""
    # Keep entry with most complete data
    best_entry = max(entries, key=lambda x: count_filled_fields(x))
    
    # Merge additional data from other entries
    for entry in entries:
        if entry != best_entry:
            merge_data(best_entry, entry)
    
    return best_entry
```

### Cross-sheet Deduplication
```python
def remove_cross_sheet_duplicates():
    """Remove duplicates across all language sheets."""
    all_repos = {}
    
    for sheet_name in get_all_sheet_names():
        sheet_data = get_sheet_data(sheet_name)
        
        for repo_name, repo_data in sheet_data.items():
            if repo_name in all_repos:
                # Handle cross-sheet duplicate
                resolve_cross_sheet_duplicate(repo_name, all_repos[repo_name], repo_data)
            else:
                all_repos[repo_name] = repo_data
```

## Data Integrity

### Validation Checks
```python
def validate_repository_data(repo_data):
    """Validate repository data before movement."""
    required_fields = ['repository', 'url', 'majority_language']
    
    for field in required_fields:
        if not repo_data.get(field):
            raise ValueError(f"Missing required field: {field}")
    
    # Validate repository name format
    if '/' not in repo_data['repository']:
        raise ValueError("Invalid repository format: must be USER/REPO")
    
    # Validate URL format
    if not repo_data['url'].startswith('https://github.com/'):
        raise ValueError("Invalid GitHub URL format")
```

### Atomic Operations
```python
def atomic_repository_movement(source_sheet, target_sheet, repo_data):
    """Perform atomic repository movement."""
    try:
        # Begin transaction
        begin_transaction()
        
        # Add to target sheet
        add_repository_to_sheet(target_sheet, repo_data)
        
        # Remove from source sheet
        remove_repository_from_sheet(source_sheet, repo_data['repository'])
        
        # Commit transaction
        commit_transaction()
        
        return True
    except Exception as e:
        # Rollback on error
        rollback_transaction()
        raise e
```

### Backup and Recovery
```python
def create_sheet_backup(sheet_name):
    """Create backup of sheet before major operations."""
    backup_data = get_sheet_data(sheet_name)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = f"backups/{sheet_name}_{timestamp}.csv"
    
    with open(backup_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(backup_data)
    
    return backup_file
```

## Sheet Organization

### Organization Process
```python
def organize_sheets():
    """Organize all language sheets."""
    client = get_gspread_client()
    spreadsheet = get_google_sheet(client)
    
    # Get all sheet names
    sheet_names = get_all_language_sheet_names()
    
    for sheet_name in sheet_names:
        print(f"Organizing sheet: {sheet_name}")
        
        # Remove duplicates within sheet
        remove_duplicates_within_sheet(client, spreadsheet, sheet_name)
        
        # Process repository movements
        organize_repositories_in_sheet(client, spreadsheet, sheet_name)
        
        print(f"✅ Completed: {sheet_name}")
```

### Repository Processing
```python
def process_repositories_in_sheet(client, spreadsheet, sheet_name):
    """Process all repositories in a sheet for organization."""
    sheet = spreadsheet.worksheet(sheet_name)
    all_values = sheet.get_all_values()
    
    for row_index, row in enumerate(all_values[1:], start=2):  # Skip header
        if len(row) >= 4:  # Ensure we have majority language column
            repo_name = row[0].strip()
            majority_language = row[3].strip()
            
            if repo_name and majority_language:
                target_sheet = get_destination_sheet_for_language(majority_language)
                
                if target_sheet != sheet_name:
                    # Repository needs to be moved
                    move_repository_to_correct_sheet(
                        client, spreadsheet, sheet_name, repo_name, majority_language
                    )
```

## Error Handling

### Sheet Access Errors
```python
def safe_sheet_access(func, *args, **kwargs):
    """Safely access sheet with error handling."""
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            if e.response.status_code == 429:  # Rate limit
                time.sleep(retry_delay * (2 ** attempt))
                continue
            else:
                raise e
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                raise e
```

### Data Validation Errors
```python
def handle_validation_errors(repo_data, sheet_name):
    """Handle repository data validation errors."""
    try:
        validate_repository_data(repo_data)
        return True
    except ValueError as e:
        print(f"⚠️ Validation error in {sheet_name}: {e}")
        print(f"   Repository: {repo_data.get('repository', 'Unknown')}")
        
        # Log error for manual review
        log_validation_error(repo_data, sheet_name, str(e))
        return False
```

### Recovery Mechanisms
```python
def recover_from_failed_operation(operation_type, repo_name, error):
    """Recover from failed sheet operations."""
    if operation_type == 'move':
        # Check if repository exists in target sheet
        if repository_exists_in_target(repo_name):
            # Remove from source sheet
            remove_from_source_sheet(repo_name)
        else:
            # Movement failed, repository should remain in source
            print(f"Movement failed for {repo_name}, keeping in source sheet")
    
    elif operation_type == 'delete':
        # Restore from backup if available
        restore_from_backup(repo_name)
```

## Performance Optimization

### Batch Operations
```python
def batch_repository_movements(movements):
    """Process multiple repository movements in batches."""
    batch_size = 50
    
    for i in range(0, len(movements), batch_size):
        batch = movements[i:i + batch_size]
        
        # Process batch
        process_movement_batch(batch)
        
        # Rate limiting
        time.sleep(1)
```

### Caching
```python
@lru_cache(maxsize=128)
def get_cached_sheet_data(sheet_name):
    """Cache sheet data to reduce API calls."""
    return fetch_sheet_data(sheet_name)

def clear_sheet_cache():
    """Clear cached sheet data."""
    get_cached_sheet_data.cache_clear()
```

### Efficient Data Structures
```python
def build_repository_index(all_sheets):
    """Build efficient index for repository lookup."""
    repo_index = {}
    
    for sheet_name, sheet_data in all_sheets.items():
        for repo_name, repo_data in sheet_data.items():
            if repo_name not in repo_index:
                repo_index[repo_name] = []
            repo_index[repo_name].append((sheet_name, repo_data))
    
    return repo_index
```

## Output Format

### Console Output
```
🔄 Starting sheet organization process...

Organizing sheet: JS/TS
  📋 Found 1,247 repositories to check
  🧹 Removing duplicates...
    ❌ Duplicate found: facebook/react (keeping row 45, removing row 156)
    ❌ Duplicate found: vuejs/vue (keeping row 67, removing row 234)
  ✅ Removed 23 duplicates
  🔄 Processing repository movements...
    ➡️ Moving scikit-learn/scikit-learn to Python sheet (Python 95%)
    ➡️ Moving spring-projects/spring-boot to Java sheet (Java 89%)
  ✅ Moved 12 repositories
✅ Completed: JS/TS

Organizing sheet: Python
  📋 Found 892 repositories to check
  🧹 Removing duplicates...
  ✅ No duplicates found
  🔄 Processing repository movements...
    ➡️ Moving facebook/react to JS/TS sheet (JavaScript 94%)
  ✅ Moved 3 repositories
✅ Completed: Python

📊 Organization Summary:
   📋 Total repositories processed: 3,456
   🧹 Duplicates removed: 45
   🔄 Repositories moved: 28
   ⏱️ Processing time: 2m 34s
   ✅ Success rate: 100%
```

### Movement Log
```
[2024-01-20 14:30:15] MOVE: facebook/react
  Source: Python sheet, Row 123
  Target: JS/TS sheet, Row 1248
  Language: JavaScript (94%)
  Status: SUCCESS

[2024-01-20 14:30:18] MOVE: scikit-learn/scikit-learn
  Source: JS/TS sheet, Row 456
  Target: Python sheet, Row 893
  Language: Python (95%)
  Status: SUCCESS

[2024-01-20 14:30:21] DUPLICATE: vuejs/vue
  Sheet: JS/TS
  Action: Removed duplicate at row 234, kept row 67
  Status: SUCCESS
```

## Integration with Workflow

### Workflow Position
1. scan_github_repos.py
2. logical_repo_checks.py
3. agentic_pr_checker_clean.py
4. update_from_LT.py
5. **sheet_organizer.py** ← You are here
6. create_repo_batches.py

### Integration Points
```python
# Called by logical_repo_checks.py
from sheet_organizer import process_single_repo_movement

# After repository evaluation
if result['language_name'] != "N/A":
    moved = process_single_repo_movement(
        client, spreadsheet, current_sheet, user_repo, result['language_name']
    )
```

### Data Flow
```
Google Sheets → sheet_organizer.py → Organized Google Sheets → Other Scripts
```

## Best Practices

### 1. Regular Organization
- Run organization weekly or after major evaluations
- Monitor for accumulation of misplaced repositories
- Verify organization accuracy regularly

### 2. Data Safety
- Always create backups before major operations
- Validate data integrity after movements
- Test organization on small datasets first

### 3. Performance Management
- Use batch operations for large datasets
- Implement proper caching for frequently accessed data
- Monitor API usage and rate limits

### 4. Error Handling
- Implement comprehensive error logging
- Provide clear error messages for debugging
- Have recovery procedures for failed operations

## Advanced Features

### Custom Organization Rules
```python
def custom_organization_rule(repo_data):
    """Apply custom organization rules."""
    # Example: Move repos with < 50% majority language to "Mixed" sheet
    if repo_data.get('language_percent', 0) < 0.5:
        return "Mixed"
    
    # Example: Keep popular repos in original sheet
    if repo_data.get('stars', 0) > 10000:
        return None  # Don't move
    
    return get_destination_sheet_for_language(repo_data['majority_language'])
```

### Quality Validation
```python
def validate_organization_quality():
    """Validate organization quality across all sheets."""
    quality_metrics = {}
    
    for sheet_name in get_all_sheet_names():
        sheet_data = get_sheet_data(sheet_name)
        misplaced_repos = find_misplaced_repositories(sheet_data, sheet_name)
        
        quality_metrics[sheet_name] = {
            'total_repos': len(sheet_data),
            'misplaced_repos': len(misplaced_repos),
            'organization_quality': 1 - (len(misplaced_repos) / len(sheet_data))
        }
    
    return quality_metrics
```

### Reporting and Analytics
```python
def generate_organization_report():
    """Generate comprehensive organization report."""
    report = {
        'timestamp': datetime.now().isoformat(),
        'sheets_processed': [],
        'total_repositories': 0,
        'movements_made': 0,
        'duplicates_removed': 0,
        'errors_encountered': []
    }
    
    # Generate detailed report
    return report
```

## Troubleshooting

### Common Issues

#### Sheet Access Problems
```python
# Verify sheet exists
def check_sheet_exists(sheet_name):
    try:
        client = get_gspread_client()
        spreadsheet = get_google_sheet(client)
        sheet = spreadsheet.worksheet(sheet_name)
        return True
    except gspread.exceptions.WorksheetNotFound:
        return False
```

#### Data Inconsistencies
```python
# Check for data inconsistencies
def validate_sheet_consistency():
    """Validate consistency across all sheets."""
    all_repos = set()
    duplicates = []
    
    for sheet_name in get_all_sheet_names():
        sheet_repos = get_repository_names(sheet_name)
        
        for repo in sheet_repos:
            if repo in all_repos:
                duplicates.append(repo)
            else:
                all_repos.add(repo)
    
    return duplicates
```

#### Performance Issues
```python
# Optimize for large sheets
def optimize_for_large_sheets():
    """Optimization strategies for large sheets."""
    # 1. Use batch operations
    # 2. Implement proper caching
    # 3. Process in chunks
    # 4. Use efficient data structures
``` 
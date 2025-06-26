# JSON to CSV Converter with Duplicate Detection

The `convert.py` script processes JSON files containing pull request data and converts them to CSV format for use in the labeling tool. It includes sophisticated duplicate detection to prevent re-processing repositories that already exist in the labeling tool.

## 🔄 Overview

This script performs the following operations:
1. **JSON to CSV Conversion** - Converts PR data from JSON to CSV format
2. **Date Filtering** - Filters PRs based on merge date (after November 1, 2024)
3. **Duplicate Detection** - Checks against existing repositories in the labeling tool
4. **Output Generation** - Creates both regular and filtered CSV files

## 📁 File Structure

The script expects and creates the following directory structure:

```
repo_checker/
├── convert.py                    # Main conversion script
├── Java_json/                    # Input JSON files for Java
│   ├── user1_repo1_pr.json
│   └── user2_repo2_pr.json
├── Java_csv/                     # Output CSV files for Java
│   ├── user1_repo1.csv
│   ├── user1_repo1_part_02.csv
│   ├── user2_repo2.csv
│   └── user2_repo2_part_02.csv
├── JavaScript_json/              # Input JSON files for JavaScript
├── JavaScript_csv/               # Output CSV files for JavaScript
├── Python_json/                  # Input JSON files for Python
├── Python_csv/                   # Output CSV files for Python
├── Go_json/                      # Input JSON files for Go
└── Go_csv/                       # Output CSV files for Go
```

## 🚀 Usage

### Basic Usage

```bash
python convert.py
```

This will:
- Automatically detect all `*_json` directories
- Process each JSON file in those directories
- Create corresponding `*_csv` directories
- Generate CSV files with duplicate detection

### Command Line Options

```bash
# Disable duplicate detection
python convert.py --no-duplicate-detection

# Force processing even if output files exist
python convert.py --force

# Combine options
python convert.py --no-duplicate-detection --force
```

## 📊 Processing Workflow

### 1. Input Detection

The script automatically detects language-specific directories:
- `Java_json/` → `Java_csv/`
- `JavaScript_json/` → `JavaScript_csv/`
- `Python_json/` → `Python_csv/`
- `Go_json/` → `Go_csv/`

### 2. JSON File Processing

For each JSON file, the script:

1. **Loads JSON Data**
   - Expects an array of PR objects
   - Extracts repository name from the first object

2. **Date Filtering**
   - Filters PRs merged after November 1, 2024
   - Uses `pr_merged_at` field for filtering
   - Skips PRs with invalid date formats

3. **File Naming**
   - Removes `_pr` suffix from input filenames
   - Example: `user_repo_pr.json` → `user_repo.csv`

### 3. Duplicate Detection

When duplicate detection is enabled (default):

1. **Repository Check**
   - Converts repository name from `USER/REPO` to `USER__REPO` format
   - Checks all labeling tool projects (IDs 40-43)
   - Projects: Python (40), JavaScript (41), Java (42), Go (43)

2. **Existing PR Detection**
   - If repository exists, fetches all existing PR IDs
   - Filters out PRs that already exist in the labeling tool
   - Creates a separate `_part_02.csv` file with non-duplicate PRs

3. **Output Files**
   - **Regular CSV**: All filtered PRs (by date)
   - **Part 02 CSV**: Non-duplicate PRs only

## 🔧 Configuration

### Labeling Tool API

The script uses the labeling tool API with these settings:

```python
LT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
BASE_BATCHES_URL = "https://eval.turing.com/api/batches..."
BASE_CONVERSATIONS_URL = "https://eval.turing.com/api/conversations..."
```

### Date Filtering

```python
FILTER_DATE = datetime(2024, 11, 1)  # November 1, 2024
```

### Project IDs

| Language | Project ID | Purpose |
|----------|------------|---------|
| Python | 40 | Python repositories |
| JavaScript | 41 | JavaScript repositories |
| Java | 42 | Java repositories |
| Go | 43 | Go repositories |

## 📋 Input Format

### JSON Structure

Each JSON file should contain an array of PR objects:

```json
[
  {
    "repo": "user/repository",
    "pr_id": 123,
    "pr_merged_at": "2024-11-15T10:30:00.000Z",
    "pr_title": "Fix bug in feature X",
    "pr_body": "This PR fixes...",
    "issue_id": 456,
    "issue_title": "Bug in feature X",
    "issue_body": "There's a bug...",
    "files": [
      {
        "filename": "src/main.py",
        "status": "modified"
      }
    ]
  }
]
```

### Required Fields

- `repo`: Repository name in `USER/REPO` format
- `pr_merged_at`: Merge date in ISO format
- `pr_id`: Pull request ID (for duplicate detection)

## 📤 Output Format

### CSV Structure

The generated CSV files contain a single column with JSON metadata:

```csv
metadata
{"repo": "user/repository", "pr_id": 123, "pr_merged_at": "2024-11-15T10:30:00.000Z", ...}
{"repo": "user/repository", "pr_id": 124, "pr_merged_at": "2024-11-16T14:20:00.000Z", ...}
```

### Output Files

For each input JSON file, the script creates:

1. **`repository.csv`** - All PRs filtered by date
2. **`repository_part_02.csv`** - Non-duplicate PRs only

## 🔍 Duplicate Detection Logic

### Repository Name Conversion

The script converts repository names for labeling tool comparison:

```python
def convert_repo_name_to_lt_format(repo_name):
    return repo_name.replace("/", "__")
```

Examples:
- `tensorflow/tensorflow` → `tensorflow__tensorflow`
- `facebook/react` → `facebook__react`

### Duplicate Check Process

1. **Fetch Existing Repositories**
   - Queries all projects (40-43) in the labeling tool
   - Collects all batch names (repository names)
   - Caches results for efficiency

2. **Repository Existence Check**
   - Converts input repository name to LT format
   - Checks against all collected repository names
   - Returns True if repository exists

3. **PR ID Filtering**
   - If repository exists, fetches all conversations for that batch
   - Extracts PR IDs from conversation metadata
   - Filters out PRs with matching IDs

### Example Scenarios

#### Scenario 1: Repository Not in Labeling Tool
```
Input: user_new/repo_new_pr.json
Output: 
- user_new/repo_new.csv (all PRs)
- user_new/repo_new_part_02.csv (all PRs - no duplicates to filter)
```

#### Scenario 2: Repository Exists in Labeling Tool
```
Input: user_existing/repo_existing_pr.json
Existing PRs: [123, 124, 125]
Input PRs: [123, 124, 126, 127]

Output:
- user_existing/repo_existing.csv (PRs: 123, 124, 126, 127)
- user_existing/repo_existing_part_02.csv (PRs: 126, 127)
```

## 🛠️ Error Handling

### API Errors
- Retries on network failures
- Continues processing other files on API errors
- Logs detailed error messages

### File Processing Errors
- Skips files with invalid JSON format
- Handles missing required fields gracefully
- Continues processing other files

### Date Parsing Errors
- Skips PRs with invalid date formats
- Logs parsing errors for debugging
- Continues with valid PRs

## 📈 Performance Considerations

### API Rate Limiting
- Uses pagination to handle large datasets
- Processes projects sequentially
- Caches repository data to minimize API calls

### Memory Usage
- Processes files one at a time
- Streams data to avoid loading large files in memory
- Clears caches between language directories

### File I/O
- Creates output directories automatically
- Uses efficient CSV writing
- Handles large JSON files gracefully

## 🔧 Troubleshooting

### Common Issues

1. **API Token Expired**
   ```
   Error: 401 Unauthorized
   Solution: Update LT_TOKEN in the script
   ```

2. **Invalid JSON Format**
   ```
   Error: JSONDecodeError
   Solution: Validate JSON file format
   ```

3. **Missing Required Fields**
   ```
   Error: KeyError: 'pr_merged_at'
   Solution: Ensure all PRs have required fields
   ```

4. **Network Timeouts**
   ```
   Error: RequestException
   Solution: Check network connection and retry
   ```

### Debug Mode

To enable verbose logging, modify the script:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 📝 Notes

- The script is designed to be idempotent - running it multiple times won't create duplicates
- Output files are overwritten only when using `--force` flag
- The script processes all language directories automatically
- Duplicate detection can be disabled for testing or when not needed
- The labeling tool API is queried for each repository to ensure accuracy 
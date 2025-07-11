# AI-Powered PR Quality Checker

## Overview

`agentic_pr_checker_clean.py` is an advanced AI-powered tool that evaluates GitHub pull requests for quality and suitability as training data. It combines logical filtering with GPT-4 analysis to identify high-quality PRs that meet specific criteria for Software Engineering Benchmarking.

## Features

### 🧠 AI-Powered Analysis
- **GPT-4 Integration**: Uses OpenAI's GPT-4 for intelligent PR quality assessment
- **Structured Evaluation**: JSON-formatted responses with reasoning
- **Issue Quality Analysis**: Evaluates linked issues for clarity and actionability
- **Multi-criteria Assessment**: Comprehensive quality evaluation framework

### 🔍 Logical Filtering
- **File Analysis**: Language-aware file filtering and validation
- **Test Requirements**: Ensures adequate test coverage (minimum 2 test files)
- **Code Change Validation**: Minimum 20 lines of non-test code changes
- **Language Gate**: Prevents cross-language contamination

### ⚡ Performance Optimization
- **Parallel Processing**: Configurable multi-threading for AI analysis
- **Progress Tracking**: Real-time progress bars and ETA calculations
- **Batch Processing**: Efficient handling of large repository sets
- **Resume Capability**: Can resume interrupted analysis

## Configuration

### Language Settings
Configure in `language_configs.json`:
```json
{
  "JavaScript": {
    "sheet_name": "JS/TS",
    "source_extensions": [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"],
    "dependency_files": ["package.json", "yarn.lock", "pnpm-lock.yaml"],
    "test_patterns": ["test", "spec"]
  }
}
```

### Script Configuration
```python
# Target language and behavior
TARGET_LANGUAGE = "JavaScript"
TARGET_GOOD_PRS = 2                    # PRs needed to pass evaluation
LLM_MODEL = "gpt-4o-mini"              # AI model for analysis
MERGED_AFTER_DATE = '2024-11-01'       # Cutoff date for PR analysis

# Parallel processing
ENABLE_PARALLEL_PROCESSING = True      # Enable/disable parallel processing
MAX_WORKERS = 4                        # Number of parallel workers
PR_PROCESSING_THRESHOLD = 1.0          # Percentage of PRs to analyze (0.0-1.0)

# Single repo mode
SINGLE_REPO_MODE = False               # Process single repository
SINGLE_REPO_URL = "https://github.com/example/repo"
```

## Usage

### Command Line Interface

```bash
# Basic usage
python src/agentic_pr_checker_clean.py

# Custom configuration
python src/agentic_pr_checker_clean.py --model gpt-4o-mini --target-good-prs 3

# Parallel processing control
python src/agentic_pr_checker_clean.py --max-workers 8 --threshold 0.5

# Single repository mode
python src/agentic_pr_checker_clean.py --single-repo https://github.com/facebook/react

# Debug mode
python src/agentic_pr_checker_clean.py --debug --debug-repo https://github.com/microsoft/vscode
```

### Available Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--model` | LLM model to use | gpt-4o-mini |
| `--target-good-prs` | Target number of good PRs | 2 |
| `--parallel` | Enable parallel processing | True |
| `--no-parallel` | Disable parallel processing | False |
| `--max-workers` | Maximum parallel workers | 4 |
| `--threshold` | PR processing threshold (0.0-1.0) | 1.0 |
| `--debug` | Enable debug mode | False |
| `--debug-repo` | Repository for debug mode | - |

### Programmatic Usage

```python
from src.agentic_pr_checker_clean import find_logically_relevant_prs, run_agentic_check_on_repo

# Find PRs that pass logical filtering
relevant_prs, total_count = find_logically_relevant_prs("facebook", "react")

# Run AI analysis on filtered PRs
passed, decisions = run_agentic_check_on_repo(relevant_prs, "facebook", "react")

# Check results
if passed:
    print(f"Repository passed with {len(decisions)} analyzed PRs")
```

## Evaluation Pipeline

### Phase 1: Logical Filtering

#### 1. PR Discovery
```python
def get_merged_prs(owner, repo, merged_after_date):
    """Fetch merged PRs since cutoff date."""
    # Query GitHub API for merged PRs
    # Filter by merge date
    # Sort by most recent
    return filtered_prs
```

#### 2. Issue Linking Validation
```python
def extract_issue_number(pr_body):
    """Extract unique issue number from PR body."""
    # Look for closing keywords: closes, fixes, resolves
    # Extract issue number from #123 format
    # Ensure single unique issue
    return issue_number
```

#### 3. Language Filtering
```python
def is_english(text):
    """Check if text is primarily English (>90% ASCII)."""
    ascii_ratio = sum(ord(c) < 128 for c in text) / len(text)
    return ascii_ratio >= 0.9
```

#### 4. File Analysis
```python
def analyze_pr_files(files):
    """Comprehensive file analysis for PR quality."""
    # Language gate - no disallowed language files
    # Minimum 2 test files required
    # Minimum 2 non-test source files required
    # Minimum 20 lines of non-test code changes
    return status, reason
```

### Phase 2: AI-Powered Analysis

#### Issue Quality Assessment
```python
AGENT_PROMPT = """
You are a senior software engineer evaluating a GitHub issue for "Good PR" suitability.

A "Good PR" meets these criteria:
1. Clear and Actionable: Specific problem/feature with enough context
2. Not a Revert: Not requesting rollback of previous changes
3. Single Issue Focus: One well-defined problem/feature
4. Primarily in English: At least 90% English content

Analyze the issue and respond with JSON:
{
  "result": "Good PR" or "Bad PR",
  "comment": "Brief explanation"
}
"""
```

#### Parallel Processing
```python
def run_parallel_agentic_checks(prs_to_check, owner, repo):
    """Run AI analysis on multiple PRs in parallel."""
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(analyze_pr, pr): pr for pr in prs_to_check}
        
        for future in as_completed(futures):
            pr_number, result = future.result()
            decisions[pr_number] = result
    
    return decisions
```

## Output Format

### CSV Reports
Generated in `repo_evaluator/{Language}_pr_reports/`:

```csv
pr_id,pr_url,issue_id,issue_url,non_test_code_changes,agent_result,agent_comment
1234,https://github.com/owner/repo/pull/1234,5678,https://github.com/owner/repo/issues/5678,145,Good PR,Clear feature request with good implementation
5678,https://github.com/owner/repo/pull/5678,9012,https://github.com/owner/repo/issues/9012,67,Bad PR,Issue description too vague
```

### Console Output
```
🔍 LOGICAL FILTERING for facebook/react...
📈 Starting logical analysis of 1,247 PRs...

Filtering: [████████████████████████████████] 1247/1247 (100.0%) | 45.2s

📊 LOGICAL FILTERING RESULTS for facebook/react:
   📈 Total PRs analyzed: 1,247
   ❌ No linked issue: 234
   ❌ Not in English: 12
   ❌ Insufficient changes: 445
   ❌ Failed file checks: 298
   ✅ Passed all logical checks: 258
   📊 Success rate: 20.7%

🚀 Starting parallel processing of 258 PRs with 4 workers...
🤖 Analyzing PRs for facebook/react: [██████████████████████████] 258/258 (100.0%) | 124.3s

📊 Parallel processing completed:
   ✅ Good PRs found: 67
   ❌ Bad PRs found: 191
   📈 Total processed: 258

🎯 SUCCESS: Target of 2 good PRs reached!
```

### Sheet Updates
Updates Google Sheets columns:
- **Column J**: PRs Count (total merged PRs)
- **Column K**: Relevant PRs Count (passed logical filtering)
- **Column L**: Good PRs > 2 (Yes/No based on AI analysis)

## Quality Filters

### Logical Filtering Criteria

#### 1. Issue Linking
- Must have unique linked issue
- Uses closing keywords (closes, fixes, resolves)
- Linked item must be issue, not PR

#### 2. Language Requirements
- Issue body must be primarily English (>90% ASCII)
- PR title and description must be English

#### 3. File Requirements
```python
# Minimum file requirements
MIN_TEST_FILES = 2
MIN_NON_TEST_FILES = 2
MIN_NON_TEST_CODE_CHANGES = 20

# Language gate - no disallowed extensions
allowed_extensions = get_source_extensions(LANGUAGE)
disallowed_extensions = ALL_SOURCE_EXT - allowed_extensions
```

#### 4. Test File Detection
```python
def _is_test_file(filepath, lang_name):
    """Relaxed test file detection."""
    # Simple check: if "test" appears anywhere in path
    if "test" in filepath.lower():
        return True
    
    # Also check for "spec" files
    if "spec" in filepath.lower():
        return True
    
    return False
```

### AI Analysis Criteria

#### Good PR Requirements
1. **Clear and Actionable**: Issue describes specific, actionable problem
2. **Not a Revert**: Not requesting rollback of previous changes
3. **Single Issue Focus**: Addresses one well-defined problem
4. **Primarily English**: At least 90% English content

#### Bad PR Indicators
- Vague or unclear issue descriptions
- Multiple unrelated changes
- Non-English content
- Simple reverts or version bumps

## Error Handling

### API Rate Limiting
```python
def make_github_api_request(url, params=None, is_retry=False):
    """GitHub API request with comprehensive error handling."""
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403 and 'rate limit exceeded' in e.response.text.lower():
            reset_time = int(e.response.headers.get('X-RateLimit-Reset', time.time() + 60))
            wait_time = max(reset_time - time.time(), 0) + 5
            time.sleep(wait_time)
            return make_github_api_request(url, params, is_retry=True)
```

### LLM Analysis Failures
```python
def run_llm_check(issue_body):
    """Run LLM analysis with error handling."""
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return parse_llm_response(response)
    except Exception as e:
        return "Bad PR", f"LLM analysis failed: {e}"
```

### Parallel Processing Errors
```python
def process_single_pr(pr):
    """Process single PR with error handling."""
    try:
        # Perform analysis
        return pr_number, {"result": result, "comment": comment}
    except Exception as e:
        return pr_number, {"result": "Bad PR", "comment": f"Error: {e}"}
```

## Performance Optimization

### Parallel Processing
```python
class ProgressTracker:
    """Thread-safe progress tracking."""
    def __init__(self, total_items, description="Processing"):
        self.total_items = total_items
        self.completed_items = 0
        self.lock = Lock()
        self.start_time = time.time()
    
    def update(self, increment=1):
        with self.lock:
            self.completed_items += increment
            self._print_progress()
```

### Memory Management
- **Streaming Processing**: Process PRs as they're found
- **Batch API Calls**: Group related API requests
- **Resource Cleanup**: Proper cleanup of connections
- **Memory Monitoring**: Track memory usage during processing

### Caching Strategy
- **GitHub API Results**: Cache PR and issue data
- **LLM Responses**: Cache AI analysis results
- **File Analysis**: Cache file parsing results

## Workflow Integration

### Complete Workflow
```python
def main():
    """Main workflow for PR quality analysis."""
    # 1. Load sheet data
    sheet_df, header = get_sheet_data(SPREADSHEET_KEY, SHEET_NAME)
    
    # 2. Find unprocessed repositories
    unprocessed_rows = find_repos_needing_analysis(sheet_df)
    
    # 3. Process each repository
    for repo_index, (sheet_row, row) in enumerate(unprocessed_rows):
        # Phase 1: Logical filtering
        relevant_prs, total_count = find_logically_relevant_prs(owner, repo)
        
        # Phase 2: AI analysis
        passed, decisions = run_agentic_check_on_repo(relevant_prs, owner, repo)
        
        # Phase 3: Generate reports
        write_prs_to_csv(owner, repo, relevant_prs, decisions)
        
        # Phase 4: Update sheets
        update_sheet_cell(SPREADSHEET_KEY, SHEET_NAME, sheet_row, 'agentic_check', "Yes" if passed else "No")
```

### Integration Points
1. **Input**: Google Sheets with repositories passing logical checks
2. **Processing**: Logical filtering + AI analysis
3. **Output**: CSV reports + Sheet updates
4. **Next Step**: Results used for batch creation

## Debug Mode

### Enable Debug Mode
```python
DEBUG_MODE = True
DEBUG_REPO_URL = "https://github.com/microsoft/vscode"
```

### Debug Output
```python
if DEBUG_MODE:
    print(f"--- Analyzing PR #{pr_number} ---")
    print(f"PR Data: {json.dumps(pr, indent=2)}")
    print(f"Issue Body: {issue_body}")
    print(f"File Analysis: {file_analysis_result}")
    print(f"AI Decision: {ai_decision}")
```

## Single Repository Mode

### Configuration
```python
SINGLE_REPO_MODE = True
SINGLE_REPO_URL = "https://github.com/facebook/react"
SINGLE_REPO_OUTPUT_DIR = "repo_evaluator/pr_reports"
```

### Usage
```python
def run_single_repo_analysis(repo_url):
    """Analyze single repository in isolation."""
    owner, repo = parse_github_url(repo_url)
    
    # Find relevant PRs
    relevant_prs, total_count = find_logically_relevant_prs(owner, repo)
    
    # Run AI analysis
    passed, decisions = run_agentic_check_on_repo(relevant_prs, owner, repo)
    
    # Generate report
    write_prs_to_csv(owner, repo, relevant_prs, decisions)
    
    return passed
```

## Best Practices

### 1. Configuration Management
- Set appropriate target PR counts per language
- Adjust processing thresholds based on repository size
- Use parallel processing for large-scale analysis

### 2. Quality Assurance
- Regularly review AI decisions for accuracy
- Monitor false positive/negative rates
- Update prompts based on analysis results

### 3. Performance Monitoring
- Track processing times per repository
- Monitor API rate limit usage
- Optimize parallel worker counts

### 4. Error Recovery
- Use resume functionality for interrupted runs
- Implement proper error logging
- Handle API failures gracefully

## Troubleshooting

### Common Issues

#### High False Positive Rate
```python
# Adjust AI prompt for stricter evaluation
AGENT_PROMPT = """
Be more conservative in evaluation. Only mark as "Good PR" if:
- Issue is extremely clear and actionable
- Implementation is substantial (not trivial)
- Changes are well-focused and coherent
"""
```

#### Processing Too Slow
```python
# Increase parallel workers
MAX_WORKERS = 8

# Reduce processing threshold
PR_PROCESSING_THRESHOLD = 0.5  # Process 50% of PRs
```

#### Memory Issues
```python
# Reduce batch sizes
BATCH_SIZE = 50

# Enable garbage collection
import gc
gc.collect()
```

### Debug Checklist
1. Verify GitHub token is valid
2. Check OpenAI API key and credits
3. Confirm sheet permissions
4. Validate language configuration
5. Test single repository mode first

## Advanced Features

### Custom Evaluation Prompts
```python
CUSTOM_PROMPT = """
Evaluate this issue for {language} repository:
- Technical complexity appropriate for {language}
- Implementation feasibility
- Testing requirements
- Documentation needs

Issue: {issue_body}
"""
```

### Threshold-based Processing
```python
def calculate_processing_threshold(total_prs):
    """Dynamic threshold based on repository size."""
    if total_prs < 50:
        return 1.0  # Process all PRs
    elif total_prs < 200:
        return 0.8  # Process 80%
    else:
        return 0.5  # Process 50%
```

### Quality Metrics
```python
def calculate_quality_metrics(decisions):
    """Calculate quality metrics from AI decisions."""
    total_analyzed = len(decisions)
    good_prs = sum(1 for d in decisions.values() if d['result'] == 'Good PR')
    
    return {
        'total_analyzed': total_analyzed,
        'good_prs': good_prs,
        'good_pr_ratio': good_prs / total_analyzed if total_analyzed > 0 else 0,
        'quality_score': calculate_quality_score(decisions)
    }
``` 
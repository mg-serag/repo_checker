# Repository Evaluation Workflow

This repository contains a comprehensive workflow for evaluating GitHub repositories for inclusion in SWE Bench. The system uses a two-stage evaluation process: **Logical Repository Checks** and **Agentic PR Checks**.

## 📊 Spreadsheet Organization

The workflow uses Google Sheets for data management and tracking. The main spreadsheet is accessible at:

**🔗 [Repository Evaluation Spreadsheet](https://docs.google.com/spreadsheets/d/1XMbstebCi1xFSwJ7cTN-DXv4jFmdH2owWBE3R7YsXK0)**

### Spreadsheet Structure

The spreadsheet contains multiple tabs for different programming languages:

| Tab Name | Language | Purpose |
|----------|----------|---------|
| `Java` | Java | Java repository evaluations |
| `JS/TS` | JavaScript/TypeScript | JavaScript and TypeScript repository evaluations |
| `Python` | Python | Python repository evaluations |
| `Go` | Go | Go repository evaluations |

### Column Layout

Each tab follows this column structure:

| Column | Header | Description |
|--------|--------|-------------|
| A | Repository | Repository name in `user/repo` format |
| B | Repository Link | Full GitHub URL |
| C | Actual Repository Link | Verified GitHub URL |
| D | Majority Language | Primary programming language |
| E | % | Language percentage |
| F | Stars | GitHub star count |
| G | LOC | Lines of code count |
| H | Already Exists | Yes, if the repo already exists in the LT |
| I | Logical Checks | Result of logical evaluation |
| J | PRs Count | Total merged PRs found |
| K | Relevant PRs Count | PRs that passed logical checks |
| L | Good PRs > 2 | Agentic evaluation result (at least two good PRs found) |
| M | Accepted | Manual Review Verdict |
| N | Why rejected | Rejection reason |
| P | Tasks Count in LT | Total conversations in labeling tool |
| Q | Improper in LT | Count of improper tasks in labeling tool |
| R | Batch Link | Direct link to labeling tool batch |
| S | Addition Date | Date when repo was added to labeling tool |

### Labeling Tool Data Integration

The logical repository checks script automatically fetches and updates data from the labeling tool API. This integration provides:


#### Update Logic

The script uses intelligent update rules based on the current "Added" column status:

**For "Yes" rows (already added):**
- Refreshes conversation counts and improper counts
- Updates addition date if available
- Does not change the "Added" status

**For "No" or empty rows:**
- If repository found in labeling tool:
  - Sets "Added" to "YES"
  - Populates all labeling tool data
  - Creates batch link
- If repository not found:
  - Sets "Added" to "NO"
  - Clears all labeling tool fields

#### Labeling Tool Projects

The script checks against these labeling tool projects:

| Language | Project ID | Purpose |
|----------|------------|---------|
| Python | 40 | Python repositories |
| JavaScript | 41 | JavaScript repositories |
| Java | 42 | Java repositories |
| Go | 43 | Go repositories |

#### Repository Name Conversion

The script converts repository names between formats:
- **GitHub format**: `user/repo`
- **Labeling tool format**: `user__repo`

Example: `tensorflow/tensorflow` → `tensorflow__tensorflow`

## 🔄 Workflow Overview

The evaluation process consists of two main stages:

1. **Logical Repository Checks** - Automated evaluation of repository metadata
2. **Agentic PR Checks** - AI-powered evaluation of pull requests

### Stage 1: Logical Repository Checks

**Script**: `src/logical_repo_checks.py`

This stage evaluates repositories based on objective criteria:

#### Check Criteria

1. **SWE Bench Duplicate Check**
   - Ensures the repository doesn't already exist in SWE Bench
   - Checks against the language-specific tab in the main spreadsheet

2. **Language Check**
   - Verifies the target language constitutes ≥70% of the codebase
   - Uses GitHub's language detection API

3. **Star Rating Check**
   - Ensures the repository has ≥400 GitHub stars
   - Indicates community adoption and quality

4. **Lines of Code (LOC) Check**
   - Dynamic requirement based on star count
   - Formula: `required_LOC = max(0, 100,000 - (stars × 200))`
   - Examples:
     - 400 stars → 20,000 LOC minimum
     - 800 stars → 60,000 LOC minimum
     - 1500+ stars → 0 LOC minimum

#### Configuration

The script uses these default settings:
- **Target Language**: Java (configurable)
- **Minimum Language Percentage**: 70%
- **Minimum Stars**: 400
- **LOC Calculation**: Dynamic based on star count

#### Output

- Updates the spreadsheet with evaluation results
- Marks repositories as "Yes" or "No" in the "Added" column
- Provides detailed failure reasons for rejected repositories

### Stage 2: Agentic PR Checks

**Script**: `src/agentic_pr_checker.py`

This stage evaluates repositories that passed logical checks by analyzing their pull requests using AI.

#### Check Criteria

1. **PR File Analysis**
   - Ensures PRs contain appropriate file types for the target language
   - Validates test file requirements (≥2 test files, ≥2 source files)
   - Checks for language-specific dependency files

2. **Issue Quality Evaluation**
   - Uses OpenAI's LLM to evaluate linked GitHub issues
   - Assesses if issues are "Good PR" candidates

#### "Good PR" Criteria

An issue is considered a "Good PR" if it:
- **Clear and Actionable**: Describes a specific, actionable problem or feature
- **Not a Revert**: Not a request to revert previous changes
- **Not a Question**: Not a simple user question or vague request for help

#### Configuration

The script supports multiple languages with specific configurations:

| Language | Sheet Name | Source Extensions | Dependency Files |
|----------|------------|-------------------|------------------|
| Java | Java | `.java` | `pom.xml`, `build.gradle`, etc. |
| JavaScript | JS/TS | `.js`, `.jsx`, `.ts`, `.tsx` | `package.json`, `yarn.lock`, etc. |
| TypeScript | JS/TS | `.ts`, `.tsx` | `package.json`, `tsconfig.json`, etc. |
| Python | Python | `.py` | `requirements.txt`, `pyproject.toml`, etc. |
| Go | Go | `.go` | `go.mod`, `go.sum`, etc. |

#### Additional Settings

- **Target Good PRs**: 2 (minimum required to pass)
- **LLM Model**: `o3-mini` (OpenAI)
- **Merged After Date**: November 1, 2024
- **Debug Mode**: Available for testing specific repositories

#### Output

- Updates the spreadsheet with PR analysis results
- Generates CSV reports in `repo_evaluator/pr_reports/`
- Marks repositories as "Yes" or "No" in the "Good PRs > 2" column

## 🚀 Running the Scripts

### Prerequisites

1. **Python Environment**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configuration Files**
   - `src/config.json` - GitHub API tokens
   - `src/creds.json` - Google Sheets service account credentials
   - `OPENAI_API_KEY` environment variable

3. **Google Sheets Access**
   - Share the spreadsheet with your service account email
   - Ensure proper permissions for read/write access

### Running Individual Scripts

#### Logical Repository Checks
```bash
cd src
python logical_repo_checks.py
```

#### Agentic PR Checks
```bash
cd src
python agentic_pr_checker.py
```

### Running the Complete Workflow

```bash
python main.py
```

This runs both stages in sequence:
1. Logical repository checks
2. Agentic PR checks

## 📁 File Structure

```
repo_checker/
├── src/
│   ├── logical_repo_checks.py    # Stage 1: Repository evaluation
│   ├── agentic_pr_checker.py     # Stage 2: PR evaluation
│   ├── config.json              # GitHub tokens
│   ├── creds.json               # Google Sheets credentials
│   └── __init__.py
├── repo_evaluator/
│   └── pr_reports/              # Generated PR analysis reports
├── main.py                      # Main workflow orchestrator
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

## 🔧 Configuration

### Language Configuration

To change the target language, modify the `TARGET_LANGUAGE` variable in the respective script:

```python
# In logical_repo_checks.py
TARGET_LANGUAGE = "Python"  # Options: Java, JavaScript, Python, Go

# In agentic_pr_checker.py  
TARGET_LANGUAGE = "Python"  # Options: Java, JavaScript, TypeScript, Python, Go
```

### API Configuration

**GitHub Tokens** (`src/config.json`):
```json
{
  "GITHUB_TOKENS": "ghp_xxxxxxxxx ghp_yyyyyyyy"
}
```

**OpenAI API Key** (Environment Variable):
```bash
export OPENAI_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"
```

## 📈 Monitoring and Results

### Spreadsheet Updates

Both scripts automatically update the spreadsheet with:
- Evaluation results
- Detailed metrics
- Failure reasons
- Processing timestamps

### Generated Reports

The agentic PR checker generates CSV reports in `repo_evaluator/pr_reports/` containing:
- PR numbers and URLs
- Issue numbers and URLs
- AI evaluation results
- Decision comments

### Console Output

Both scripts provide detailed console output including:
- Processing progress
- Evaluation details
- Error messages
- Summary statistics

## 🛠️ Troubleshooting

### Common Issues

1. **Rate Limiting**: The scripts use token rotation to handle GitHub API rate limits
2. **Sheet Access**: Ensure the service account has proper permissions
3. **API Keys**: Verify all API keys are valid and have appropriate permissions
4. **Language Detection**: Some repositories may have ambiguous language detection

### Debug Mode

Enable debug mode in `agentic_pr_checker.py`:
```python
DEBUG_MODE = True
DEBUG_REPO_URL = "https://github.com/your-repo/name"
```

## 📝 Notes

- The workflow is designed to be resumable - it only processes unprocessed rows
- Both scripts include comprehensive error handling and logging
- The system supports multiple programming languages with language-specific configurations
- Results are automatically saved to Google Sheets for easy tracking and collaboration 
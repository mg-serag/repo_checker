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

#### Data Fetched from Labeling Tool

1. **Total Conversations (Column P)**
   - Total number of conversations/tasks in the labeling tool
   - Fetched from `countOfConversations` field in batch data

2. **Improper Tasks Count (Column Q)**
   - Number of tasks marked as "improper" in the labeling tool
   - Fetched from `batchStats.improper` field

3. **Addition Date (Column S)**
   - Date when the repository was added to the labeling tool
   - Parsed from `createdAt` field in batch data

4. **Batch Link (Column R)**
   - Direct link to view the batch in the labeling tool
   - Format: `https://eval.turing.com/batches/{batch_id}/view`

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

1. **Labeling Tool Duplicate Check**
   - Ensures the repository doesn't already exist in the labeling tool
   - Checks against the language-specific project in the labeling tool
   - Converts repository names from `USER/REPO` to `USER__REPO` format

2. **Sheet Duplicate Check**
   - Identifies duplicate repositories within the same sheet
   - Marks all instances except the first occurrence as duplicates
   - Prevents processing of duplicate entries

3. **Language Check**
   - Verifies the target language constitutes ≥70% of the codebase
   - Uses GitHub's language detection API
   - Language-specific thresholds for each target language

4. **Star Rating Check**
   - Ensures the repository has ≥400 GitHub stars
   - Indicates community adoption and quality

5. **Lines of Code (LOC) Check**
   - Dynamic requirement based on star count using language-specific thresholds
   - Examples for Go (current target):
     - 400 stars → 150,000 LOC minimum
     - 450 stars → 120,000 LOC minimum
     - 500 stars → 100,000 LOC minimum
     - 800 stars → 75,000 LOC minimum
     - 1500+ stars → 60,000 LOC minimum

#### Configuration

The script uses these language-specific settings:
- **Target Language**: Go (configurable)
- **Minimum Language Percentage**: 70%
- **Minimum Stars**: 400
- **LOC Calculation**: Dynamic based on star count with language-specific thresholds
- **Labeling Tool Project ID**: 43 (Go project)

#### Output

- Updates the spreadsheet with evaluation results
- Marks repositories as "Yes", "No", or "Manual" in the "Logical Checks" column
- "Manual" indicates LOC check errors requiring human review
- Provides detailed failure reasons for rejected repositories
- Automatically updates labeling tool data (conversations, improper counts, dates)

### Stage 2: Agentic PR Checks

**Script**: `src/agentic_pr_checker.py`

This stage evaluates repositories that passed logical checks by analyzing their pull requests using AI.

#### Check Criteria

1. **PR File Analysis**
   - Ensures PRs contain appropriate file types for the target language
   - Validates test file requirements (≥2 test files, ≥2 source files)
   - Checks for language-specific dependency files
   - Prevents files from other programming languages

2. **Issue Quality Evaluation**
   - Uses OpenAI's LLM to evaluate linked GitHub issues
   - Assesses if issues are "Good PR" candidates
   - Analyzes issue clarity and actionability

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
- **Target Language**: Java (configurable)

#### Output

- Updates the spreadsheet with PR analysis results
- Generates CSV reports in `repo_evaluator/pr_reports/`
- Marks repositories as "Yes" or "No" in the "Good PRs > 2" column
- Provides detailed PR analysis and issue evaluation results

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
TARGET_LANGUAGE = "Python"  # Options: 'Java', 'JavaScript', 'Python', 'Go'

# In agentic_pr_checker.py  
TARGET_LANGUAGE = "Python"  # Options: 'Java', 'JavaScript', 'TypeScript', 'Python', 'Go'
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
- Labeling tool integration data

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
- Column mapping information

## 🛠️ Troubleshooting

### Common Issues

1. **Rate Limiting**: The scripts use token rotation to handle GitHub API rate limits
2. **Sheet Access**: Ensure the service account has proper permissions
3. **API Keys**: Verify all API keys are valid and have appropriate permissions
4. **Language Detection**: Some repositories may have ambiguous language detection
5. **Column Mapping**: Scripts automatically detect column headers and fall back to defaults

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
- Labeling tool integration provides real-time data synchronization
- Duplicate detection prevents processing of existing repositories 
# Repository Checker & SWE-Bench Tool Suite

## Overview & Philosophy

This repository contains a comprehensive suite of tools designed to systematically discover, evaluate, and process GitHub repositories for Software Engineering Benchmarking (SWE-Bench) purposes. The core philosophy is to create a **reproducible, scalable, and language-agnostic pipeline** that can:

1. **Discover** high-quality repositories across multiple programming languages
2. **Evaluate** them against strict criteria (stars, language percentage, lines of code)
3. **Analyze** their pull requests using AI-powered quality assessment
4. **Organize** the data in a structured, trackable format
5. **Process** the results into usable datasets for machine learning training

## Repository Structure

```
repo_checker/
├── README.md                           # This file
├── main.py                             # Main workflow orchestrator
├── requirements.txt                    # Python dependencies
├── src/                                # Core scripts
│   ├── config_utils.py                 # Centralized configuration
│   ├── language_configs.json           # Language-specific settings
│   ├── scan_github_repos.py            # Repository discovery
│   ├── logical_repo_checks.py          # Repository evaluation
│   ├── agentic_pr_checker_clean.py     # AI-powered PR analysis
│   ├── update_from_LT.py               # Labeling tool integration
│   ├── sheet_organizer.py              # Repository organization
│   ├── recall_conversations.py         # Data retrieval
│   ├── get_improper_reasons.py         # Quality analysis
│   ├── create_repo_batches.py          # Batch creation
│   └── convert.py                      # Data format conversion
├── cache/                              # Local caching for API calls
├── processing_reports/                 # Processing statistics
├── {Language}_csv/                     # CSV outputs by language
├── {Language}_json/                    # JSON outputs by language
├── repo_evaluator/                     # Evaluation results
│   ├── {Language}_pr_reports/          # PR analysis reports
│   └── ...
└── obsolete/                           # Deprecated scripts (reference only)
    ├── pr_sourcing_linin.py
    ├── swe-bench_LT (obsolete).py
    ├── agentic_pr_checker (obsolete).py
    └── get_existing_repos.py
```

## Google Sheets Integration & Naming Conventions

### Spreadsheet Structure

The system uses Google Sheets as the central coordination hub with language-specific tabs:

- **Java** - Java repositories
- **JS/TS** - JavaScript/TypeScript repositories  
- **Python** - Python repositories
- **Go** - Go repositories
- **C/C++** - C/C++ repositories
- **Rust** - Rust repositories
- **C#** - C# repositories
- **Ruby** - Ruby repositories

### Column Structure (Critical for Tracking)

Each sheet follows a standardized column structure:

| Column | Header | Purpose |
|--------|--------|---------|
| A | Repository | USER/REPO format |
| B | Empty | Reserved |
| C | Actual Repository Link | Full GitHub URL |
| D | Majority Language | Detected primary language |
| E | % | Language percentage |
| F | Stars | GitHub star count |
| G | LOC | Lines of code |
| H | Already Exists | Duplicate tracking |
| I | Logical Checks | Pass/Fail/Manual |
| J | PRs Count | Total PR count |
| K | Relevant PRs Count | Filtered PR count |
| L | Good PRs > 2 | AI quality assessment |
| M-N | Reserved | Future use |
| O | Added | Added to labeling tool |
| P | Tasks Count in LT | Labeling tool metrics |
| Q | Improper in LT | Quality metrics |
| R | Batch Link | Labeling tool batch URL |
| S | Addition Date | When added to LT |

### Naming Convention Requirements

**CRITICAL**: The repository naming must follow the exact format:
- **Format**: `USER/REPO` (e.g., `facebook/react`, `microsoft/vscode`)
- **Case Sensitive**: Must match GitHub exactly
- **No Spaces**: No leading/trailing spaces
- **Consistency**: Same format across all sheets and outputs

This naming convention enables:
- ✅ Duplicate prevention across sheets
- ✅ Proper repository movement between language sheets
- ✅ Accurate labeling tool integration
- ✅ Correct API calls and data matching

## Core Scripts Overview

### 🔍 Repository Discovery & Evaluation

#### [`scan_github_repos.py`](src/docs/README_scan_github_repos.md)
**Purpose**: Discovers and adds high-quality repositories to Google Sheets
- Searches GitHub API for repositories meeting star/language criteria
- Checks for modern toolchains (package.json, pom.xml, etc.)
- Writes results in batches to prevent data loss
- Handles rate limiting and resume functionality

#### [`logical_repo_checks.py`](src/docs/README_logical_repo_checks.md)
**Purpose**: Evaluates repositories against strict quality criteria
- **Language Analysis**: Detects majority language and percentage
- **Star Rating**: Validates minimum star requirements
- **LOC Analysis**: Counts lines of code with thresholds
- **Duplicate Detection**: Prevents duplicate processing
- **Repository Movement**: Moves repos to correct language sheets

#### [`agentic_pr_checker_clean.py`](src/docs/README_agentic_pr_checker.md)
**Purpose**: AI-powered analysis of pull requests for quality assessment
- **Logical Filtering**: File analysis, test requirements, change thresholds
- **AI Analysis**: GPT-4 evaluation of PR/issue quality
- **Parallel Processing**: Efficient batch processing
- **Quality Metrics**: Identifies "Good PRs" for training data

### 🔧 Data Management & Integration

#### [`update_from_LT.py`](src/docs/README_update_from_LT.md)
**Purpose**: Synchronizes data with Labeling Tool
- Fetches batch data from labeling tool API
- Updates sheet columns with task counts and metrics
- Handles different project IDs per language
- Maintains data consistency

#### [`sheet_organizer.py`](src/docs/README_sheet_organizer.md)
**Purpose**: Organizes repositories by majority language
- **Auto-movement**: Moves repos to correct language sheets
- **Duplicate Management**: Removes duplicates within sheets
- **Data Integrity**: Preserves repository data during moves
- **Language Detection**: Based on actual code analysis

#### [`convert.py`](src/docs/README_convert.md)
**Purpose**: Converts JSON data to CSV format with processing
- **Format Conversion**: JSON → CSV with proper headers
- **Data Enrichment**: Adds metadata and processing statistics
- **Batch Processing**: Handles multiple files efficiently
- **Report Generation**: Creates processing reports

### 📊 Analysis & Reporting

#### [`recall_conversations.py`](src/docs/README_recall_conversations.md)
**Purpose**: Retrieves conversation data from labeling tool
- Fetches conversation details by ID
- Extracts metadata and content
- Exports to CSV for analysis
- Handles bulk conversation retrieval

#### [`get_improper_reasons.py`](src/docs/README_get_improper_reasons.md)
**Purpose**: Analyzes improper task reasons
- Fetches improper task data from labeling tool
- Extracts rejection reasons and patterns
- Generates CSV reports for quality improvement
- Helps identify common issues

#### [`create_repo_batches.py`](src/docs/README_create_repo_batches.md)
**Purpose**: Creates batches in labeling tool
- **Job Management**: Starts and monitors processing jobs
- **Batch Creation**: Creates labeling tool batches
- **Sheet Integration**: Reads repositories from Google Sheets
- **Workflow Automation**: End-to-end batch creation

## Output Structure & Configurations

### Language-Specific Outputs

Each language has dedicated output directories:

```
{Language}_csv/          # CSV files for each repo
{Language}_json/         # JSON files for each repo
repo_evaluator/
└── {Language}_pr_reports/  # PR analysis reports
```

### Configuration Files

- **`language_configs.json`**: Language-specific settings
- **`config.json`**: API keys and global settings
- **`creds.json`**: Google Sheets service account credentials

### Report Types

1. **Repository Reports**: Basic repo information (CSV/JSON)
2. **PR Reports**: Detailed PR analysis with AI evaluation
3. **Processing Reports**: Statistics and processing metrics
4. **Quality Reports**: Improper task analysis and conversation data

## Complete Workflow

### 1. Discovery Phase
```bash
python src/scan_github_repos.py --language JavaScript --count 1000
```

### 2. Evaluation Phase
   ```bash
python src/logical_repo_checks.py
```

### 3. Analysis Phase
```bash
python src/agentic_pr_checker_clean.py
```

### 4. Integration Phase
```bash
python src/update_from_LT.py
python src/sheet_organizer.py
```

### 5. Batch Creation Phase
```bash
python src/create_repo_batches.py
```

### 6. Data Processing Phase
```bash
python src/convert.py
```

## Main Workflow Orchestrator

Use `main.py` to run the complete workflow:

```bash
python main.py
```

This executes all phases in sequence with proper error handling and logging.

## Language Support

Currently supported languages with their configurations:

- **Java**: Maven/Gradle projects, .java files
- **JavaScript**: npm/yarn projects, .js/.jsx files  
- **TypeScript**: npm/yarn projects, .ts/.tsx files
- **Python**: pip/conda projects, .py files
- **Go**: go.mod projects, .go files
- **C/C++**: CMake/Makefile projects, .c/.cpp/.h files
- **Rust**: Cargo projects, .rs files
- **C#**: .NET projects, .cs files
- **Ruby**: Gem projects, .rb files

## Key Features

### 🔄 Automatic Repository Movement
Repositories are automatically moved to the correct language sheet based on their majority language.

### 🚫 Duplicate Prevention
Multiple layers of duplicate detection prevent processing the same repository multiple times.

### 📊 Quality Metrics
AI-powered analysis ensures only high-quality repositories and PRs are selected for training.

### 🔧 Resume Functionality
All scripts support resuming from interruptions without losing progress.

### 📈 Scalable Processing
Parallel processing and batch operations handle large-scale repository analysis.

## Obsolete Scripts (Reference Only)

The following scripts are deprecated but kept for reference:

- **`pr_sourcing_linin.py`**: Early PR sourcing prototype
- **`swe-bench_LT (obsolete).py`**: Legacy SWE-Bench integration
- **`agentic_pr_checker (obsolete).py`**: Old version of PR checker
- **`get_existing_repos.py`**: Legacy repository fetching

## Getting Started

1. **Setup Dependencies**:
```bash
   pip install -r requirements.txt
   ```

2. **Configure API Keys**:
   - Create `config.json` with GitHub and OpenAI tokens
   - Add `creds.json` for Google Sheets access

3. **Run Complete Workflow**:
```bash
   python main.py
   ```

4. **Monitor Progress**:
   - Check Google Sheets for real-time updates
   - Review processing reports in `processing_reports/`
   - Monitor output directories for results

## Documentation

For detailed documentation of each script, see the individual README files in the `src/` directory:

- [Repository Scanning](src/docs/README_scan_github_repos.md)
- [Logical Evaluation](src/docs/README_logical_repo_checks.md)
- [AI PR Analysis](src/docs/README_agentic_pr_checker.md)
- [Labeling Tool Integration](src/docs/README_update_from_LT.md)
- [Repository Organization](src/docs/README_sheet_organizer.md)
- [Data Conversion](src/docs/README_convert.md)
- [Conversation Recall](src/docs/README_recall_conversations.md)
- [Quality Analysis](src/docs/README_get_improper_reasons.md)
- [Batch Creation](src/docs/README_create_repo_batches.md)

## Contributing

When adding new languages or features:

1. Update `language_configs.json` with new language settings
2. Follow the established naming conventions
3. Add appropriate test patterns and file extensions
4. Update this README with new language support
5. Create corresponding documentation files

## Support

For issues or questions:
1. Check the individual script README files
2. Review the configuration files
3. Verify Google Sheets permissions and structure
4. Ensure all API keys are properly configured 
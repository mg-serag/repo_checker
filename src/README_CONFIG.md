# Configuration System

This directory now uses a centralized configuration system to manage all tokens and settings across the scripts.

## Configuration File: `config.json`

The `config.json` file contains all the configuration settings used by the scripts:

```json
{
  "lt_token": "your_labeling_tool_token_here",
  "github_token": "your_github_token_here",
  "openai_api_key": "your_openai_api_key_here",
  "spreadsheet_key": "your_google_sheets_key_here",
  "project_ids": {
    "python": 40,
    "javascript": 41,
    "java": 42,
    "go": 43,
    "cpp": 44,
    "rust": 45
  }
}
```

## Configuration Utility: `config_utils.py`

The `config_utils.py` module provides functions to access configuration settings:

### Available Functions:

- `get_lt_token()` - Get the Labeling Tool token
- `get_github_token()` - Get the GitHub token (falls back to environment variable)
- `get_openai_api_key()` - Get the OpenAI API key (falls back to environment variable)
- `get_spreadsheet_key()` - Get the Google Sheets spreadsheet key
- `get_project_id(language)` - Get the project ID for a specific language
- `get_config()` - Get the entire configuration dictionary

### Usage Example:

```python
from config_utils import get_lt_token, get_project_id

# Get LT token
lt_token = get_lt_token()

# Get project ID for Java
java_project_id = get_project_id('java')
```

## Updated Scripts

The following scripts have been updated to use the centralized configuration:

1. **`update_from_LT.py`** - Uses LT token, spreadsheet key, and project IDs
2. **`logical_repo_checks.py`** - Uses LT token, spreadsheet key, and project IDs
3. **`get_improper_reasons.py`** - Uses LT token and project ID
4. **`get_existing_repos.py`** - Uses LT token and project ID
5. **`agentic_pr_checker.py`** - Uses GitHub token, OpenAI API key, and spreadsheet key

## Environment Variable Fallback

For security-sensitive tokens (GitHub and OpenAI), the system will:
1. First try to read from `config.json`
2. If not found, fall back to environment variables:
   - `GITHUB_TOKEN`
   - `OPENAI_API_KEY`

## Setup Instructions

1. Copy the `config.json` file to the `src/` directory
2. Update the tokens in `config.json` with your actual values:
   - Replace `"your_labeling_tool_token_here"` with your actual LT token
   - Replace `"your_github_token_here"` with your GitHub token (optional, can use env var)
   - Replace `"your_openai_api_key_here"` with your OpenAI API key (optional, can use env var)
   - Replace `"your_google_sheets_key_here"` with your Google Sheets key

3. Ensure the `config_utils.py` file is in the same directory as your scripts

## Security Notes

- Keep your `config.json` file secure and don't commit it to version control
- Consider using environment variables for sensitive tokens instead of storing them in the config file
- The `creds.json` file for Google Sheets authentication should remain separate and secure

## Benefits

- **Centralized Management**: All configuration in one place
- **Easy Updates**: Change tokens once, affects all scripts
- **Environment Fallback**: Flexible token management
- **Type Safety**: Proper error handling for missing configuration
- **Maintainability**: Easier to manage and update settings 
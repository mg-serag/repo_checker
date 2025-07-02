# Language Configuration System

This directory now uses a centralized language configuration system to manage all language-specific settings across the scripts.

## Configuration File: `language_configs.json`

The `language_configs.json` file contains comprehensive language configurations for all supported programming languages:

### Structure

```json
{
  "languages": {
    "LanguageName": {
      "display_name": "Human Readable Name",
      "sheet_name": "Google Sheets Tab Name",
      "target_language": "Language Identifier",
      "github_language": "GitHub API Language",
      "evaluation": {
        "min_percentage": 70,
        "min_stars": 400,
        "loc_thresholds": {
          "400": 150000,
          "450": 120000,
          "500": 100000,
          "800": 75000,
          "1500": 60000
        }
      },
      "file_analysis": {
        "source_extensions": [".ext1", ".ext2"],
        "dependency_files": ["file1", "file2"],
        "test_patterns": ["pattern1", "pattern2"]
      }
    }
  },
  "global_settings": {
    "non_code_extensions": [".md", ".txt", ...],
    "universal_test_extensions": [".snap", ".spec"],
    "test_directories": ["/test/", "/tests/", "/spec/"]
  }
}
```

### Supported Languages

- **Java** - Java repositories
- **JavaScript** - JavaScript/TypeScript repositories  
- **TypeScript** - TypeScript repositories
- **Python** - Python repositories
- **Go** - Go repositories
- **C/C++** - C and C++ repositories
- **Rust** - Rust repositories

## Configuration Utility Functions

The `config_utils.py` module provides comprehensive functions for accessing language configurations:

### Language Configuration Functions

- `get_language_config(language_name)` - Get complete config for a language
- `get_all_languages()` - Get all available language configurations
- `get_language_sheet_name(language_name)` - Get Google Sheets tab name
- `get_language_target_language(language_name)` - Get target language identifier
- `get_language_github_language(language_name)` - Get GitHub API language

### Evaluation Functions

- `get_language_evaluation_config(language_name)` - Get evaluation settings
- `get_loc_thresholds(language_name)` - Get LOC thresholds for star counts
- `get_language_evaluation_settings(language_name)` - Get complete evaluation settings

### File Analysis Functions

- `get_source_extensions(language_name)` - Get source file extensions
- `get_dependency_files(language_name)` - Get dependency file names
- `get_test_patterns(language_name)` - Get test file patterns

### Global Settings Functions

- `get_non_code_extensions()` - Get non-code file extensions
- `get_universal_test_extensions()` - Get universal test extensions
- `get_test_directories()` - Get test directory patterns

## Usage Examples

### Basic Language Configuration

```python
from config_utils import get_language_config, get_language_sheet_name

# Get complete Java configuration
java_config = get_language_config('Java')

# Get sheet name for Python
sheet_name = get_language_sheet_name('Python')  # Returns 'Python'
```

### Evaluation Settings

```python
from config_utils import get_language_evaluation_settings

# Get evaluation settings for JavaScript
eval_settings = get_language_evaluation_settings('JavaScript')
print(f"Min stars: {eval_settings['min_stars']}")
print(f"Min percentage: {eval_settings['min_percentage']}%")
print(f"LOC thresholds: {eval_settings['loc_thresholds']}")
```

### File Analysis

```python
from config_utils import get_source_extensions, get_dependency_files

# Get Python file extensions
extensions = get_source_extensions('Python')  # {'.py'}

# Get Java dependency files
deps = get_dependency_files('Java')  # {'pom.xml', 'build.gradle', ...}
```

## Updated Scripts

The following scripts have been updated to use the centralized language configuration:

### 1. **`logical_repo_checks.py`**
- Uses centralized evaluation settings (min_percentage, min_stars, loc_thresholds)
- Uses centralized project IDs
- Uses centralized sheet names

### 2. **`agentic_pr_checker.py`**
- Uses centralized file analysis settings (source_extensions, dependency_files)
- Uses centralized test patterns
- Uses centralized global settings

## Configuration Sections

### Evaluation Configuration
Used by `logical_repo_checks.py` for repository evaluation:

```json
"evaluation": {
  "min_percentage": 70,        // Minimum language percentage
  "min_stars": 400,           // Minimum GitHub stars
  "loc_thresholds": {         // LOC requirements by star count
    "400": 150000,
    "450": 120000,
    "500": 100000,
    "800": 75000,
    "1500": 60000
  }
}
```

### File Analysis Configuration
Used by `agentic_pr_checker.py` for PR file analysis:

```json
"file_analysis": {
  "source_extensions": [".java"],           // Source file extensions
  "dependency_files": ["pom.xml", ...],     // Build/dependency files
  "test_patterns": ["test.java"]            // Test file patterns
}
```

### Global Settings
Used by both scripts for common file processing:

```json
"global_settings": {
  "non_code_extensions": [".md", ".txt", ...],     // Non-code files
  "universal_test_extensions": [".snap", ".spec"],  // Universal test files
  "test_directories": ["/test/", "/tests/", "/spec/"]  // Test directories
}
```

## Benefits

### 🔧 **Maintainability**
- Single source of truth for all language settings
- Easy to add new languages or modify existing ones
- Consistent configuration across all scripts

### 🚀 **Flexibility**
- Easy to adjust evaluation criteria per language
- Simple to add new file extensions or patterns
- Centralized test file detection

### 📊 **Consistency**
- All scripts use the same language definitions
- Consistent sheet names and project IDs
- Unified file analysis rules

### 🛡️ **Error Handling**
- Graceful fallbacks if configuration files are missing
- Clear error messages for missing languages
- Type-safe configuration access

## Adding New Languages

To add a new language:

1. **Add to `language_configs.json`**:
```json
"NewLanguage": {
  "display_name": "New Language",
  "sheet_name": "NewLanguage",
  "target_language": "NewLanguage",
  "github_language": "NewLanguage",
  "evaluation": {
    "min_percentage": 70,
    "min_stars": 400,
    "loc_thresholds": {
      "400": 150000,
      "450": 120000,
      "500": 100000,
      "800": 75000,
      "1500": 60000
    }
  },
  "file_analysis": {
    "source_extensions": [".nl"],
    "dependency_files": ["config.nl"],
    "test_patterns": ["_test.nl"]
  }
}
```

2. **Add project ID to `config.json`**:
```json
"project_ids": {
  "newlanguage": 46
}
```

3. **Update scripts** - The scripts will automatically use the new configuration!

## Migration Notes

- All existing functionality is preserved
- Backward compatibility maintained
- Fallback values provided for missing configurations
- No breaking changes to existing scripts 
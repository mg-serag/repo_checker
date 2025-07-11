# Obsolete Scripts (Reference Only)

## Overview

This directory contains several scripts that are no longer actively used in the current workflow but are preserved for reference purposes. These scripts represent earlier implementations or experimental approaches that may contain useful patterns or ideas.

## Obsolete Scripts

### `pr_sourcing_linin.py`
- **Purpose**: Earlier version of PR sourcing logic
- **Status**: Replaced by `agentic_pr_checker_clean.py`
- **Notes**: Contains experimental filtering approaches

### `swe-bench_LT (obsolete).py`
- **Purpose**: Legacy SWE-Bench integration
- **Status**: Functionality integrated into main workflow
- **Notes**: Historical implementation for reference

### `agentic_pr_checker (obsolete).py`
- **Purpose**: Original AI-powered PR checker
- **Status**: Replaced by `agentic_pr_checker_clean.py`
- **Notes**: Contains earlier prompt engineering approaches

### `get_existing_repos.py`
- **Purpose**: Repository existence checking
- **Status**: Functionality integrated into `logical_repo_checks.py`
- **Notes**: Standalone utility for repo validation

## Important Notes

⚠️ **DO NOT USE THESE SCRIPTS IN PRODUCTION**

These scripts are included for:
- **Reference purposes**: Understanding evolution of the codebase
- **Code archaeology**: Recovering useful patterns or logic
- **Learning**: Seeing different approaches to similar problems
- **Debugging**: Understanding legacy behavior

## Current Alternatives

| Obsolete Script | Current Alternative | Notes |
|----------------|-------------------|--------|
| `pr_sourcing_linin.py` | `agentic_pr_checker_clean.py` | Cleaner implementation |
| `swe-bench_LT (obsolete).py` | `main.py` workflow | Integrated approach |
| `agentic_pr_checker (obsolete).py` | `agentic_pr_checker_clean.py` | Improved performance |
| `get_existing_repos.py` | `logical_repo_checks.py` | Integrated functionality |

## Migration Notes

If you need to understand or migrate functionality from these scripts:

1. **Check the current implementation first** - the functionality may already exist
2. **Review the git history** - understand why changes were made
3. **Test thoroughly** - obsolete scripts may have known issues
4. **Update dependencies** - these scripts may use outdated libraries

## Maintenance

These scripts are **not maintained** and may:
- Have security vulnerabilities
- Use deprecated APIs
- Contain bugs that were fixed in newer versions
- Not work with current dependencies

For any active development, always use the current, maintained scripts listed in the main README. 
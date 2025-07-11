# Repository Batch Creator

## Overview

`create_repo_batches.py` automatically creates batches of repositories in the Labeling Tool platform. It processes repositories that have passed quality checks and organizes them into manageable batches for annotation and evaluation.

## Features

- **Automated Batch Creation**: Creates batches from qualified repositories
- **Quality Filtering**: Only processes repositories with "Good PRs > 2" = "Yes"
- **Batch Organization**: Creates 5-repository batches by default
- **Error Handling**: Robust error handling for API failures
- **Progress Tracking**: Real-time progress monitoring

## Usage

```bash
# Create batches for all qualified repositories
python src/create_repo_batches.py

# Create batches for specific language
python src/create_repo_batches.py --language JavaScript

# Custom batch size
python src/create_repo_batches.py --batch-size 10

# Dry run (preview without creating)
python src/create_repo_batches.py --dry-run
```

## Configuration

Configure project IDs and batch settings in `language_configs.json`:

```json
{
  "JavaScript": {
    "project_id": 41,
    "batch_size": 5,
    "sheet_name": "JS/TS"
  }
}
```

## Workflow Integration

- **Input**: Repositories with "Good PRs > 2" = "Yes"
- **Processing**: Creates batches via Labeling Tool API
- **Output**: Batch IDs and confirmation of creation
- **Next Step**: Repositories become available for annotation

## Error Handling

- API rate limiting with exponential backoff
- Duplicate batch prevention
- Comprehensive error logging
- Graceful failure recovery

See full documentation in the script comments for detailed API usage and configuration options. 
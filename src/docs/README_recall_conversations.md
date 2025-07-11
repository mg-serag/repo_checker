# Conversation Recall Tool

## Overview

`recall_conversations.py` analyzes and recalls conversations from the Labeling Tool platform. It helps identify conversation patterns, quality metrics, and provides insights into annotation quality and worker performance.

## Features

- **Conversation Analysis**: Retrieves and analyzes LT conversations
- **Quality Metrics**: Calculates conversation quality scores
- **Pattern Detection**: Identifies common conversation patterns
- **Data Export**: Exports conversation data for analysis
- **Performance Tracking**: Monitors annotation performance

## Usage

```bash
# Recall conversations for all projects
python src/recall_conversations.py

# Recall conversations for specific project
python src/recall_conversations.py --project-id 41

# Export to CSV
python src/recall_conversations.py --export conversations.csv

# Analyze quality patterns
python src/recall_conversations.py --analyze-quality
```

## Configuration

Configure project IDs and analysis settings in `language_configs.json`:

```json
{
  "analysis": {
    "min_conversation_length": 10,
    "quality_threshold": 0.8,
    "export_format": "csv"
  }
}
```

## Output Format

- **CSV Export**: Conversation data in tabular format
- **Quality Reports**: Analysis of conversation quality
- **Performance Metrics**: Worker and project performance data
- **Pattern Analysis**: Common conversation patterns and issues

## Integration

- **Input**: Conversations from Labeling Tool API
- **Processing**: Analysis and pattern detection
- **Output**: Reports and insights for quality improvement
- **Usage**: Quality assurance and process optimization

See full documentation in the script comments for detailed API usage and analysis options. 
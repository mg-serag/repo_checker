# Improper Reasons Analyzer

## Overview

`get_improper_reasons.py` analyzes and categorizes reasons why pull requests are marked as "improper" in the Labeling Tool. It helps identify patterns in quality issues and provides insights for improving PR selection criteria.

## Features

- **Reason Analysis**: Categorizes improper PR reasons
- **Pattern Detection**: Identifies common quality issues
- **Statistical Analysis**: Provides detailed statistics on improper reasons
- **Report Generation**: Creates comprehensive analysis reports
- **Trend Analysis**: Tracks reason trends over time

## Usage

```bash
# Analyze improper reasons for all projects
python src/get_improper_reasons.py

# Analyze specific project
python src/get_improper_reasons.py --project-id 41

# Export detailed report
python src/get_improper_reasons.py --export-report reasons_analysis.csv

# Show top reasons only
python src/get_improper_reasons.py --top-reasons 10
```

## Configuration

Configure analysis parameters in `language_configs.json`:

```json
{
  "analysis": {
    "min_reason_frequency": 5,
    "categorization_rules": {
      "language_issues": ["non-english", "translation"],
      "code_quality": ["poor_code", "incomplete"],
      "scope_issues": ["too_broad", "multiple_issues"]
    }
  }
}
```

## Output Format

- **Reason Categories**: Grouped by common themes
- **Frequency Analysis**: Most common improper reasons
- **Trend Reports**: Changes in reason patterns over time
- **Language-specific Analysis**: Breakdown by programming language
- **Actionable Insights**: Recommendations for improving PR selection

## Integration

- **Input**: Improper conversation data from Labeling Tool
- **Processing**: Categorization and statistical analysis
- **Output**: Reports and insights for quality improvement
- **Usage**: Refining PR selection criteria and quality standards

See full documentation in the script comments for detailed analysis methods and configuration options. 
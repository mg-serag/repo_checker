#!/usr/bin/env python3
"""
Helper script to switch between different language configurations for the agentic PR checker.
"""

import json
import os
import sys
import shutil
from pathlib import Path

# Available language configurations
LANGUAGE_CONFIGS = {
    'java': 'agentic_config_java.json',
    'javascript': 'agentic_config.json',  # Default is JavaScript
    'js': 'agentic_config.json',
    'typescript': 'agentic_config_typescript.json',
    'ts': 'agentic_config_typescript.json',
    'python': 'agentic_config_python.json',
    'py': 'agentic_config_python.json',
    'go': 'agentic_config_go.json'
}

def print_available_languages():
    """Print available language options."""
    print("Available languages:")
    print("  java, javascript (js), typescript (ts), python (py), go")
    print()

def switch_language(language):
    """Switch to the specified language configuration."""
    language_lower = language.lower()
    
    if language_lower not in LANGUAGE_CONFIGS:
        print(f"❌ Error: Language '{language}' not supported.")
        print_available_languages()
        return False
    
    source_config = LANGUAGE_CONFIGS[language_lower]
    target_config = 'agentic_config.json'
    
    # Check if source config exists
    if not os.path.exists(source_config):
        print(f"❌ Error: Configuration file '{source_config}' not found.")
        return False
    
    try:
        # Copy the language-specific config to the main config
        shutil.copy2(source_config, target_config)
        
        # Read and display the new configuration
        with open(target_config, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        print(f"✅ Successfully switched to {config['target_language']} configuration.")
        print(f"📁 Source: {source_config}")
        print(f"📁 Target: {target_config}")
        print(f"🎯 Target Language: {config['target_language']}")
        print(f"📊 Sheet Name: {get_sheet_name(config['target_language'])}")
        print()
        
        return True
        
    except Exception as e:
        print(f"❌ Error switching configuration: {e}")
        return False

def get_sheet_name(language):
    """Get the sheet name for a given language."""
    sheet_names = {
        'Java': 'Java',
        'JavaScript': 'JS/TS',
        'TypeScript': 'JS/TS',
        'Python': 'Python',
        'Go': 'Go'
    }
    return sheet_names.get(language, 'Unknown')

def show_current_config():
    """Show the current configuration."""
    config_file = 'agentic_config.json'
    
    if not os.path.exists(config_file):
        print("❌ No configuration file found.")
        return
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        print("Current Configuration:")
        print(f"  Target Language: {config['target_language']}")
        print(f"  Sheet Name: {get_sheet_name(config['target_language'])}")
        print(f"  Debug Mode: {config['debug_mode']}")
        print(f"  Target Good PRs: {config['target_good_prs']}")
        print(f"  LLM Model: {config['llm_model']}")
        print()
        
    except Exception as e:
        print(f"❌ Error reading configuration: {e}")

def main():
    """Main function."""
    print("🔄 Agentic PR Checker - Language Switcher")
    print("=" * 50)
    
    if len(sys.argv) < 2:
        print("Usage: python switch_language.py <language>")
        print()
        show_current_config()
        print_available_languages()
        return
    
    language = sys.argv[1]
    
    if language.lower() in ['help', '-h', '--help']:
        print("Usage: python switch_language.py <language>")
        print()
        print_available_languages()
        return
    
    success = switch_language(language)
    
    if success:
        print("You can now run the agentic PR checker with the new configuration:")
        print("  python agentic_pr_checker.py")

if __name__ == "__main__":
    main() 
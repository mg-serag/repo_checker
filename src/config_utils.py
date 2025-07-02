import json
import os
from typing import Dict, Any, Optional

# Path to the configuration file
CONFIG_FILE_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

def load_config() -> Dict[str, Any]:
    """
    Load configuration from config.json file.
    
    Returns:
        Dict containing configuration settings
        
    Raises:
        FileNotFoundError: If config.json doesn't exist
        json.JSONDecodeError: If config.json is invalid JSON
    """
    if not os.path.exists(CONFIG_FILE_PATH):
        raise FileNotFoundError(f"Configuration file not found at {CONFIG_FILE_PATH}")
    
    with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_lt_token() -> str:
    """
    Get the Labeling Tool token from configuration.
    
    Returns:
        LT token string
        
    Raises:
        KeyError: If lt_token is not found in config
        FileNotFoundError: If config file doesn't exist
    """
    config = load_config()
    return config['lt_token']

def get_github_token() -> Optional[str]:
    """
    Get the GitHub token from configuration.
    
    Returns:
        GitHub token string or None if not set
    """
    try:
        config = load_config()
        return config.get('github_token') or os.getenv('GITHUB_TOKEN')
    except (FileNotFoundError, KeyError):
        return os.getenv('GITHUB_TOKEN')

def get_openai_api_key() -> Optional[str]:
    """
    Get the OpenAI API key from configuration.
    
    Returns:
        OpenAI API key string or None if not set
    """
    try:
        config = load_config()
        return config.get('openai_api_key') or os.getenv('OPENAI_API_KEY')
    except (FileNotFoundError, KeyError):
        return os.getenv('OPENAI_API_KEY')

def get_spreadsheet_key() -> str:
    """
    Get the Google Sheets spreadsheet key from configuration.
    
    Returns:
        Spreadsheet key string
        
    Raises:
        KeyError: If spreadsheet_key is not found in config
    """
    config = load_config()
    return config['spreadsheet_key']

def get_project_id(language: str) -> int:
    """
    Get the project ID for a specific language from configuration.
    
    Args:
        language: Language name (python, javascript, java, go, cpp, rust)
        
    Returns:
        Project ID integer
        
    Raises:
        KeyError: If language or project_ids not found in config
    """
    config = load_config()
    language_lower = language.lower()
    return config['project_ids'][language_lower]

def get_config() -> Dict[str, Any]:
    """
    Get the entire configuration dictionary.
    
    Returns:
        Complete configuration dictionary
    """
    return load_config()

# --- Language Configuration Functions ---

def load_language_configs() -> Dict[str, Any]:
    """
    Load language configurations from language_configs.json file.
    
    Returns:
        Dict containing language configurations
        
    Raises:
        FileNotFoundError: If language_configs.json doesn't exist
        json.JSONDecodeError: If language_configs.json is invalid JSON
    """
    language_config_path = os.path.join(os.path.dirname(__file__), 'language_configs.json')
    if not os.path.exists(language_config_path):
        raise FileNotFoundError(f"Language configuration file not found at {language_config_path}")
    
    with open(language_config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_language_config(language_name: str) -> Dict[str, Any]:
    """
    Get configuration for a specific language.
    
    Args:
        language_name: Name of the language (e.g., 'Java', 'JavaScript', 'Python', etc.)
        
    Returns:
        Language configuration dictionary
        
    Raises:
        KeyError: If language not found in configuration
    """
    configs = load_language_configs()
    language_key = language_name.replace('/', '').replace('+', '')  # Handle 'C/C++' -> 'C/C++'
    return configs['languages'][language_key]

def get_all_languages() -> Dict[str, Any]:
    """
    Get all available language configurations.
    
    Returns:
        Dictionary of all language configurations
    """
    configs = load_language_configs()
    return configs['languages']

def get_global_settings() -> Dict[str, Any]:
    """
    Get global settings for language processing.
    
    Returns:
        Global settings dictionary
    """
    configs = load_language_configs()
    return configs['global_settings']

def get_language_evaluation_config(language_name: str) -> Dict[str, Any]:
    """
    Get evaluation configuration for a specific language.
    
    Args:
        language_name: Name of the language
        
    Returns:
        Evaluation configuration dictionary
    """
    lang_config = get_language_config(language_name)
    return lang_config['evaluation']

def get_language_file_analysis_config(language_name: str) -> Dict[str, Any]:
    """
    Get file analysis configuration for a specific language.
    
    Args:
        language_name: Name of the language
        
    Returns:
        File analysis configuration dictionary
    """
    lang_config = get_language_config(language_name)
    return lang_config['file_analysis']

def get_language_sheet_name(language_name: str) -> str:
    """
    Get the Google Sheets tab name for a specific language.
    
    Args:
        language_name: Name of the language
        
    Returns:
        Sheet name string
    """
    lang_config = get_language_config(language_name)
    return lang_config['sheet_name']

def get_language_target_language(language_name: str) -> str:
    """
    Get the target language identifier for a specific language.
    
    Args:
        language_name: Name of the language
        
    Returns:
        Target language string
    """
    lang_config = get_language_config(language_name)
    return lang_config['target_language']

def get_language_github_language(language_name: str) -> str:
    """
    Get the GitHub API language identifier for a specific language.
    
    Args:
        language_name: Name of the language
        
    Returns:
        GitHub language string
    """
    lang_config = get_language_config(language_name)
    return lang_config['github_language']

def get_source_extensions(language_name: str) -> set:
    """
    Get source file extensions for a specific language.
    
    Args:
        language_name: Name of the language
        
    Returns:
        Set of source file extensions
    """
    file_config = get_language_file_analysis_config(language_name)
    return set(file_config['source_extensions'])

def get_dependency_files(language_name: str) -> set:
    """
    Get dependency file names for a specific language.
    
    Args:
        language_name: Name of the language
        
    Returns:
        Set of dependency file names
    """
    file_config = get_language_file_analysis_config(language_name)
    return set(file_config['dependency_files'])

def get_test_patterns(language_name: str) -> list:
    """
    Get test file patterns for a specific language.
    
    Args:
        language_name: Name of the language
        
    Returns:
        List of test file patterns
    """
    file_config = get_language_file_analysis_config(language_name)
    return file_config['test_patterns']

def get_loc_thresholds(language_name: str) -> Dict[int, int]:
    """
    Get LOC thresholds for a specific language.
    
    Args:
        language_name: Name of the language
        
    Returns:
        Dictionary mapping star counts to LOC thresholds
    """
    eval_config = get_language_evaluation_config(language_name)
    # Convert string keys to integers
    return {int(k): v for k, v in eval_config['loc_thresholds'].items()}

def get_non_code_extensions() -> set:
    """
    Get global non-code file extensions.
    
    Returns:
        Set of non-code file extensions
    """
    global_settings = get_global_settings()
    return set(global_settings['non_code_extensions'])

def get_universal_test_extensions() -> set:
    """
    Get universal test file extensions.
    
    Returns:
        Set of universal test file extensions
    """
    global_settings = get_global_settings()
    return set(global_settings['universal_test_extensions'])

def get_test_directories() -> list:
    """
    Get test directory patterns.
    
    Returns:
        List of test directory patterns
    """
    global_settings = get_global_settings()
    return global_settings['test_directories'] 
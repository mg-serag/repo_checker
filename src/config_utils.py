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

def get_swe_token() -> str:
    """
    Get the SWE Bench token from configuration.
    
    Returns:
        SWE token string
        
    Raises:
        KeyError: If SWE_TOKEN is not found in config
        FileNotFoundError: If config file doesn't exist
    """
    config = load_config()
    return config['SWE_TOKEN']

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

def get_gspread_client() -> "gspread.client.Client":
    """
    Get the gspread client using service account credentials.
    """
    import gspread

    config = load_config()
    credentials_path = config.get('google_credentials_path', 'creds.json')
    
    config_dir = os.path.dirname(CONFIG_FILE_PATH)
    abs_credentials_path = os.path.join(config_dir, credentials_path)

    if not os.path.exists(abs_credentials_path):
        raise FileNotFoundError(f"Google credentials file not found at {abs_credentials_path}")

    return gspread.service_account(filename=abs_credentials_path)


def get_google_sheet(client: "gspread.client.Client") -> "gspread.Spreadsheet":
    """
    Get the Google Sheet object using the spreadsheet key from config.
    """
    import gspread
    spreadsheet_key = get_spreadsheet_key()
    return client.open_by_key(spreadsheet_key)

def get_project_id(language: str) -> int:
    """
    Get the project ID for a specific language from configuration.
    
    Args:
        language: Language name (python, javascript, java, go, cpp, rust, etc.)
        
    Returns:
        Project ID integer
        
    Raises:
        KeyError: If language not found in config
    """
    # Normalize language name and use the language configuration function
    normalized_name = _normalize_language_name(language)
    return get_language_project_id(normalized_name)

def get_config() -> Dict[str, Any]:
    """
    Get the entire configuration dictionary.
    
    Returns:
        Complete configuration dictionary
    """
    return load_config()

# --- Language Configuration Functions ---

def _normalize_language_name(language_name: str) -> str:
    """
    Normalize language name to match configuration keys.
    
    Args:
        language_name: Input language name (case-insensitive)
        
    Returns:
        Normalized language name that matches configuration keys
        
    Raises:
        KeyError: If language not found in mapping
    """
    # Map common language names to the proper language config names
    language_mapping = {
        'javascript': 'JavaScript',
        'typescript': 'TypeScript',
        'java': 'Java',
        'python': 'Python',
        'go': 'Go',
        'cpp': 'C/C++',
        'c++': 'C/C++',
        'c': 'C/C++',
        'c/c++': 'C/C++',
        'rust': 'Rust',
        'csharp': 'C#',
        'c#': 'C#',
        'ruby': 'Ruby'
    }
    
    # Get the proper language name from the mapping
    language_lower = language_name.lower().strip()
    proper_language_name = language_mapping.get(language_lower, language_name)
    
    # If the mapping didn't change the name, check if it exists as-is in the config
    if proper_language_name == language_name:
        # Check if the language exists in the configuration
        configs = load_language_configs()
        if language_name in configs['languages']:
            return language_name
        else:
            # Try to find a case-insensitive match
            for config_key in configs['languages'].keys():
                if config_key.lower() == language_lower:
                    return config_key
            
            # If no match found, raise an error with available languages
            available_languages = list(configs['languages'].keys())
            raise KeyError(f"Language '{language_name}' not found in configuration. Available languages: {available_languages}")
    
    return proper_language_name

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
    # Normalize language name to match configuration keys
    normalized_name = _normalize_language_name(language_name)
    
    configs = load_language_configs()
    return configs['languages'][normalized_name]

def get_all_language_configs() -> Dict[str, Any]:
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

def get_language_evaluation_settings(language_name: str) -> Dict[str, Any]:
    """
    Get complete evaluation settings for a specific language.
    This combines evaluation config and LOC thresholds.
    
    Args:
        language_name: Name of the language
        
    Returns:
        Dictionary containing complete evaluation settings
    """
    eval_config = get_language_evaluation_config(language_name)
    loc_thresholds = get_loc_thresholds(language_name)
    
    return {
        'min_percentage': eval_config['min_percentage'],
        'min_stars': eval_config['min_stars'],
        'loc_thresholds': loc_thresholds
    }

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

def get_language_project_id(language_name: str) -> int:
    """
    Get the Labeling Tool project ID for a specific language.
    
    Args:
        language_name: Name of the language
        
    Returns:
        Project ID integer
    """
    lang_config = get_language_config(language_name)
    return lang_config['project_id']

def get_language_json_folder(language_name: str) -> str:
    """
    Get the JSON folder path for a specific language.
    
    Args:
        language_name: Name of the language
        
    Returns:
        JSON folder path string pointing to batches directory
    """
    lang_config = get_language_config(language_name)
    folder_name = lang_config['file_analysis']['json_folder']
    
    # Get the root directory (parent of src directory)
    src_dir = os.path.dirname(__file__)
    root_dir = os.path.dirname(src_dir)
    
    # Construct full path to batches directory
    batches_dir = os.path.join(root_dir, 'batches')
    json_folder = os.path.join(batches_dir, folder_name)
    
    return json_folder

def get_language_csv_folder(language_name: str) -> str:
    """
    Get the CSV folder path for a specific language.
    
    Args:
        language_name: Name of the language
        
    Returns:
        CSV folder path string pointing to batches directory
    """
    lang_config = get_language_config(language_name)
    folder_name = lang_config['file_analysis']['csv_folder']
    
    # Get the root directory (parent of src directory)
    src_dir = os.path.dirname(__file__)
    root_dir = os.path.dirname(src_dir)
    
    # Construct full path to batches directory
    batches_dir = os.path.join(root_dir, 'batches')
    csv_folder = os.path.join(batches_dir, folder_name)
    
    return csv_folder

def get_test_directories() -> list:
    """
    Get test directory patterns.
    
    Returns:
        List of test directory patterns
    """
    global_settings = get_global_settings()
    return global_settings['test_directories'] 
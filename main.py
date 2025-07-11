#!/usr/bin/env python3
"""
Main Workflow Orchestrator for Repository Checker & SWE-Bench Tool Suite

This script orchestrates the complete workflow for discovering, evaluating, and processing 
GitHub repositories for SWE-Bench purposes. It coordinates all phases of the pipeline:

1. Repository Discovery (scan_github_repos.py)
2. Logical Evaluation (logical_repo_checks.py)
3. AI-Powered Analysis (agentic_pr_checker_clean.py)
4. Data Synchronization (update_from_LT.py)
5. Repository Organization (sheet_organizer.py)
6. Batch Creation (create_repo_batches.py) - Optional
7. Data Processing (convert.py)

Usage:
    python main.py [options]

Options:
    --skip-scan         Skip repository scanning phase
    --skip-logical      Skip logical evaluation phase
    --skip-agentic      Skip AI analysis phase
    --skip-update       Skip labeling tool update phase
    --skip-organize     Skip repository organization phase
    --skip-convert      Skip data conversion phase
    --create-batches    Enable batch creation (commented by default)
    --language          Target language for processing
    --dry-run          Preview workflow without executing
    --config           Path to configuration file
"""

import os
import sys
import time
import argparse
import traceback
import subprocess
from datetime import datetime
from pathlib import Path

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Import all workflow components
import scan_github_repos
import logical_repo_checks
import agentic_pr_checker_clean
import update_from_LT
import sheet_organizer
import create_repo_batches
import convert
from config_utils import get_all_language_configs

# Workflow configuration
WORKFLOW_CONFIG = {
    'phases': {
        'discovery': {
            'name': 'Repository Discovery',
            'description': 'Scan GitHub for high-quality repositories',
            'module': scan_github_repos,
            'critical': False  # Can be skipped if repos already exist
        },
        'evaluation': {
            'name': 'Logical Evaluation',
            'description': 'Evaluate repositories against quality criteria',
            'module': logical_repo_checks,
            'critical': True  # Core evaluation step
        },
        'analysis': {
            'name': 'AI-Powered Analysis',
            'description': 'Analyze PRs using AI for quality assessment',
            'module': agentic_pr_checker_clean,
            'critical': True  # Core analysis step
        },
        'synchronization': {
            'name': 'Data Synchronization',
            'description': 'Update data from labeling tool',
            'module': update_from_LT,
            'critical': False  # Data enhancement step
        },
        'organization': {
            'name': 'Repository Organization',
            'description': 'Organize repositories by majority language',
            'module': sheet_organizer,
            'critical': False  # Organization step
        },
        'batch_creation': {
            'name': 'Batch Creation',
            'description': 'Create batches in labeling tool',
            'module': create_repo_batches,
            'critical': False,  # Optional step
            'default_enabled': False  # Commented by default
        },
        'conversion': {
            'name': 'Data Conversion',
            'description': 'Convert JSON data to CSV format',
            'module': convert,
            'critical': False  # Final processing step
        }
    },
    'dependencies': {
        'evaluation': ['discovery'],  # Evaluation depends on discovery
        'analysis': ['evaluation'],   # Analysis depends on evaluation
        'batch_creation': ['analysis'],  # Batch creation depends on analysis
        'conversion': ['batch_creation']  # Conversion depends on batch creation
    }
}

class WorkflowOrchestrator:
    """Orchestrates the complete repository evaluation workflow."""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.start_time = time.time()
        self.completed_phases = []
        self.failed_phases = []
        self.skipped_phases = []
        
        # Create logs directory
        self.logs_dir = Path('logs')
        self.logs_dir.mkdir(exist_ok=True)
        
        # Setup logging
        self.log_file = self.logs_dir / f'workflow_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        
    def log(self, message, level='INFO'):
        """Log a message with timestamp."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f'[{timestamp}] {level}: {message}'
        print(log_entry)
        
        # Write to log file
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')
    
    def print_workflow_banner(self):
        """Print workflow banner with configuration."""
        banner = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                   Repository Checker & SWE-Bench Tool Suite                 ║
║                            Main Workflow Orchestrator                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
        print(banner)
        self.log("=" * 80)
        self.log("WORKFLOW ORCHESTRATOR STARTED")
        self.log("=" * 80)
        
        # Print configuration
        self.log("Configuration:")
        for key, value in self.config.items():
            self.log(f"  {key}: {value}")
        
        # Print supported languages
        try:
            languages = list(get_all_language_configs().keys())
            self.log(f"Supported Languages: {', '.join(languages)}")
        except Exception as e:
            self.log(f"Could not load language configs: {e}", 'WARNING')
        
        self.log("=" * 80)
    
    def check_dependencies(self):
        """Check if all required dependencies are available."""
        self.log("Checking dependencies...")
        
        # Check Python version
        if sys.version_info < (3, 8):
            self.log("Python 3.8 or higher is required", 'ERROR')
            return False
        
        # Check required files
        required_files = [
            'src/config_utils.py',
            'src/language_configs.json',
            'requirements.txt'
        ]
        
        for file_path in required_files:
            if not os.path.exists(file_path):
                self.log(f"Required file missing: {file_path}", 'ERROR')
                return False
        
        # Check API keys (basic check)
        try:
            from config_utils import get_github_token, get_openai_api_key
            if not get_github_token():
                self.log("GitHub token not configured", 'WARNING')
            if not get_openai_api_key():
                self.log("OpenAI API key not configured", 'WARNING')
        except Exception as e:
            self.log(f"Could not check API keys: {e}", 'WARNING')
        
        self.log("Dependencies check completed")
        return True
    
    def run_phase(self, phase_name, phase_config):
        """Run a single phase of the workflow."""
        self.log(f"Starting Phase: {phase_config['name']}")
        self.log(f"Description: {phase_config['description']}")
        
        if self.config.get('dry_run', False):
            self.log("DRY RUN: Skipping actual execution", 'INFO')
            self.skipped_phases.append(phase_name)
            return True
        
        try:
            # Run the phase
            phase_start_time = time.time()
            
            if hasattr(phase_config['module'], 'main'):
                phase_config['module'].main()
            else:
                self.log(f"Module {phase_config['module'].__name__} has no main() function", 'WARNING')
            
            phase_duration = time.time() - phase_start_time
            self.log(f"Phase completed in {phase_duration:.2f} seconds")
            self.completed_phases.append(phase_name)
            return True
            
    except Exception as e:
            self.log(f"Phase failed: {e}", 'ERROR')
            self.log(f"Full traceback: {traceback.format_exc()}", 'ERROR')
            self.failed_phases.append(phase_name)
            return False
    
    def check_phase_dependencies(self, phase_name):
        """Check if all dependencies for a phase are satisfied."""
        dependencies = WORKFLOW_CONFIG['dependencies'].get(phase_name, [])
        
        for dep in dependencies:
            if dep not in self.completed_phases:
                self.log(f"Dependency not satisfied: {phase_name} requires {dep}", 'WARNING')
                return False
        
        return True
    
    def run_workflow(self):
        """Run the complete workflow."""
        self.print_workflow_banner()
        
        # Check dependencies
        if not self.check_dependencies():
            self.log("Dependency check failed. Aborting workflow.", 'ERROR')
        return False

        # Get phases to run
        phases_to_run = []
        for phase_name, phase_config in WORKFLOW_CONFIG['phases'].items():
            # Check if phase should be skipped
            skip_key = f'skip_{phase_name.replace("_", "-")}'
            if self.config.get(skip_key, False):
                self.log(f"Skipping phase: {phase_config['name']} (user requested)")
                self.skipped_phases.append(phase_name)
                continue
            
            # Check if phase is enabled by default
            if not phase_config.get('default_enabled', True):
                enable_key = f'enable_{phase_name.replace("_", "-")}'
                if not self.config.get(enable_key, False):
                    self.log(f"Skipping phase: {phase_config['name']} (disabled by default)")
                    self.skipped_phases.append(phase_name)
                    continue
            
            phases_to_run.append((phase_name, phase_config))
        
        self.log(f"Phases to run: {[p[1]['name'] for p in phases_to_run]}")
        
        # Run phases
        for phase_name, phase_config in phases_to_run:
            self.log("=" * 60)
            self.log(f"PHASE: {phase_config['name'].upper()}")
            self.log("=" * 60)
            
            # Check dependencies
            if not self.check_phase_dependencies(phase_name):
                if phase_config['critical']:
                    self.log(f"Critical phase {phase_name} cannot run due to unmet dependencies", 'ERROR')
                    return False
                else:
                    self.log(f"Skipping non-critical phase {phase_name} due to unmet dependencies", 'WARNING')
                    self.skipped_phases.append(phase_name)
                    continue
            
            # Run the phase
            success = self.run_phase(phase_name, phase_config)
            
            if not success:
                if phase_config['critical']:
                    self.log(f"Critical phase {phase_name} failed. Aborting workflow.", 'ERROR')
                    return False
                else:
                    self.log(f"Non-critical phase {phase_name} failed. Continuing workflow.", 'WARNING')
        
        # Print final summary
        self.print_final_summary()
        return len(self.failed_phases) == 0
    
    def print_final_summary(self):
        """Print final workflow summary."""
        total_time = time.time() - self.start_time
        
        summary = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                              WORKFLOW SUMMARY                               ║
╚══════════════════════════════════════════════════════════════════════════════╝

🕐 Total Runtime: {total_time:.2f} seconds
📊 Phases Summary:
   ✅ Completed: {len(self.completed_phases)} phases
   ❌ Failed: {len(self.failed_phases)} phases
   ⏭️ Skipped: {len(self.skipped_phases)} phases

"""
        
        if self.completed_phases:
            summary += "✅ Completed Phases:\n"
            for phase in self.completed_phases:
                phase_name = WORKFLOW_CONFIG['phases'][phase]['name']
                summary += f"   • {phase_name}\n"
        
        if self.failed_phases:
            summary += "\n❌ Failed Phases:\n"
            for phase in self.failed_phases:
                phase_name = WORKFLOW_CONFIG['phases'][phase]['name']
                summary += f"   • {phase_name}\n"
        
        if self.skipped_phases:
            summary += "\n⏭️ Skipped Phases:\n"
            for phase in self.skipped_phases:
                phase_name = WORKFLOW_CONFIG['phases'][phase]['name']
                summary += f"   • {phase_name}\n"
        
        if len(self.failed_phases) == 0:
            summary += "\n🎉 WORKFLOW COMPLETED SUCCESSFULLY! 🎉"
        else:
            summary += "\n⚠️  WORKFLOW COMPLETED WITH ERRORS"
        
        summary += f"\n\n📋 Log file: {self.log_file}"
        summary += "\n" + "=" * 80
        
        print(summary)
        self.log(summary)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Repository Checker & SWE-Bench Tool Suite - Main Workflow Orchestrator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python main.py                          # Run complete workflow
    python main.py --skip-scan              # Skip repository scanning
    python main.py --create-batches         # Include batch creation
    python main.py --dry-run                # Preview workflow
    python main.py --language JavaScript    # Target specific language
        """
    )
    
    # Phase control options
    parser.add_argument('--skip-discovery', action='store_true',
                       help='Skip repository discovery phase')
    parser.add_argument('--skip-evaluation', action='store_true',
                       help='Skip logical evaluation phase')
    parser.add_argument('--skip-analysis', action='store_true',
                       help='Skip AI analysis phase')
    parser.add_argument('--skip-synchronization', action='store_true',
                       help='Skip data synchronization phase')
    parser.add_argument('--skip-organization', action='store_true',
                       help='Skip repository organization phase')
    parser.add_argument('--skip-conversion', action='store_true',
                       help='Skip data conversion phase')
    
    # Optional phase enablement
    parser.add_argument('--create-batches', action='store_true',
                       help='Enable batch creation phase (disabled by default)')
    
    # Configuration options
    parser.add_argument('--language', type=str,
                       help='Target language for processing')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview workflow without executing')
    parser.add_argument('--config', type=str,
                       help='Path to configuration file')
    
    return parser.parse_args()


def main():
    """Main entry point for the workflow orchestrator."""
    args = parse_arguments()
    
    # Build configuration from arguments
    config = {
        'skip_discovery': args.skip_discovery,
        'skip_evaluation': args.skip_evaluation,
        'skip_analysis': args.skip_analysis,
        'skip_synchronization': args.skip_synchronization,
        'skip_organization': args.skip_organization,
        'skip_conversion': args.skip_conversion,
        'enable_batch_creation': args.create_batches,  # Commented by default
        'language': args.language,
        'dry_run': args.dry_run,
        'config_file': args.config
    }
    
    # Create and run orchestrator
    orchestrator = WorkflowOrchestrator(config)
    success = orchestrator.run_workflow()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


def run_repository_workflow():
    """
    Execute the complete repository processing workflow.
    
    This function orchestrates the entire pipeline:
    1. Repository scanning and discovery
    2. Logical evaluation and filtering
    3. AI-powered PR analysis
    4. Data synchronization with Labeling Tool
    5. Sheet organization and cleanup
    6. Optional: Batch creation for annotation
    7. Data format conversion and reporting
    """
    
    print("🚀 Starting Repository Checker & SWE-Bench Workflow")
    print("=" * 60)
    
    workflow_start_time = time.time()
    
    try:
        # Phase 1: Repository Scanning
        print("\n📡 Phase 1: Repository Scanning")
        print("-" * 40)
        result = subprocess.run([
            sys.executable, "src/scan_github_repos.py"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Repository scanning failed: {result.stderr}")
            return False
        print("✅ Repository scanning completed successfully")
        
        # Phase 2: Logical Evaluation
        print("\n🔍 Phase 2: Logical Repository Evaluation")
        print("-" * 40)
        result = subprocess.run([
            sys.executable, "src/logical_repo_checks.py"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Logical evaluation failed: {result.stderr}")
            return False
        print("✅ Logical evaluation completed successfully")
        
        # Phase 3: AI-Powered PR Analysis
        print("\n🤖 Phase 3: AI-Powered PR Analysis")
        print("-" * 40)
        result = subprocess.run([
            sys.executable, "src/agentic_pr_checker_clean.py"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ AI PR analysis failed: {result.stderr}")
            return False
        print("✅ AI PR analysis completed successfully")
        
        # Phase 4: Data Synchronization
        print("\n🔄 Phase 4: Labeling Tool Data Synchronization")
        print("-" * 40)
        result = subprocess.run([
            sys.executable, "src/update_from_LT.py"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Data synchronization failed: {result.stderr}")
            return False
        print("✅ Data synchronization completed successfully")
        
        # Phase 5: Sheet Organization
        print("\n📋 Phase 5: Sheet Organization")
        print("-" * 40)
        result = subprocess.run([
            sys.executable, "src/sheet_organizer.py"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Sheet organization failed: {result.stderr}")
            return False
        print("✅ Sheet organization completed successfully")
        
        # Phase 6: Batch Creation (Commented - Manual Activation)
        print("\n📦 Phase 6: Batch Creation (Optional)")
        print("-" * 40)
        print("⚠️  Batch creation is commented out for manual activation")
        print("   Uncomment the following lines to create 5 batches:")
        print("   # result = subprocess.run([")
        print("   #     sys.executable, \"src/create_repo_batches.py\"")
        print("   # ], capture_output=True, text=True)")
        print("💡 To activate: Remove comments and run again")
        
        # Uncomment the following lines to activate batch creation
        # result = subprocess.run([
        #     sys.executable, "src/create_repo_batches.py"
        # ], capture_output=True, text=True)
        # 
        # if result.returncode != 0:
        #     print(f"❌ Batch creation failed: {result.stderr}")
        #     return False
        # print("✅ Batch creation completed successfully")
        
        # Phase 7: Data Format Conversion
        print("\n💾 Phase 7: Data Format Conversion")
        print("-" * 40)
        result = subprocess.run([
            sys.executable, "src/convert.py"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Data conversion failed: {result.stderr}")
            return False
        print("✅ Data conversion completed successfully")
        
        # Workflow Complete
        workflow_end_time = time.time()
        total_time = workflow_end_time - workflow_start_time
        
        print("\n🎉 Repository Workflow Completed Successfully!")
        print("=" * 60)
        print(f"⏱️  Total execution time: {total_time:.2f} seconds")
        print(f"📊 Check processing_reports/ for detailed statistics")
        print(f"📁 Check language-specific CSV files for converted data")
        print(f"🔗 Check Google Sheets for updated repository data")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Critical error in workflow: {e}")
        return False


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Repository Checker & SWE-Bench Tool Suite")
    parser.add_argument("--workflow", action="store_true", help="Run complete workflow")
    parser.add_argument("--phase", type=str, help="Run specific phase only")
    parser.add_argument("--list-phases", action="store_true", help="List available phases")
    
    args = parser.parse_args()
    
    if args.list_phases:
        print("Available phases:")
        print("1. scan       - Repository scanning and discovery")
        print("2. logical    - Logical repository evaluation")
        print("3. agentic    - AI-powered PR analysis")
        print("4. sync       - Labeling Tool data synchronization")
        print("5. organize   - Sheet organization and cleanup")
        print("6. batch      - Batch creation (manual activation)")
        print("7. convert    - Data format conversion")
        print("\nUse --phase <phase_name> to run individual phases")
        
    elif args.phase:
        phase_map = {
            "scan": "src/scan_github_repos.py",
            "logical": "src/logical_repo_checks.py",
            "agentic": "src/agentic_pr_checker_clean.py",
            "sync": "src/update_from_LT.py",
            "organize": "src/sheet_organizer.py",
            "batch": "src/create_repo_batches.py",
            "convert": "src/convert.py"
        }
        
        if args.phase in phase_map:
            print(f"🔄 Running phase: {args.phase}")
            result = subprocess.run([sys.executable, phase_map[args.phase]])
            sys.exit(result.returncode)
        else:
            print(f"❌ Unknown phase: {args.phase}")
            print("Use --list-phases to see available phases")
            sys.exit(1)
    
    elif args.workflow:
        success = run_repository_workflow()
        sys.exit(0 if success else 1)
    
    else:
        # Default behavior - run individual main function
        main()

# =============================================================================
# BATCH CREATION EXAMPLE (COMMENTED BY DEFAULT)
# =============================================================================
# 
# To enable batch creation, uncomment the following lines and run:
# python main.py --create-batches
#
# This will create 5 batches in the labeling tool after successful analysis.
# The create_repo_batches.py script handles the complete batch creation process
# including job management, PR processing, and labeling tool integration.
#
# Example usage for batch creation:
# 
# from src.create_repo_batches import main as create_batches_main
# 
# def create_sample_batches():
#     """Create 5 sample batches for testing/demonstration."""
#     print("🚀 Creating sample batches in labeling tool...")
#     
#     # This would create batches for the first 5 qualifying repositories
#     # found in the Google Sheets after successful analysis
#     
#     try:
#         create_batches_main()
#         print("✅ Batch creation completed successfully!")
#     except Exception as e:
#         print(f"❌ Batch creation failed: {e}")
#         return False
#     
#     return True
#
# Uncomment the above function and call it in the workflow if needed.
# =============================================================================

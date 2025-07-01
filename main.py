# TODO: Main Workflow Orchestration
#
# This file needs to be updated to orchestrate the entire repository evaluation workflow.
# The following two major tasks need to be implemented:
#
# TASK 1: ORCHESTRATE THE ENTIRE WORKFLOW
# =======================================
# - Modify individual scripts to support orchestration from main.py
# - Implement proper error handling and rollback mechanisms
# - Add configuration management for the entire workflow
# - Ensure proper sequencing of all stages:
#   1. Repository scanning (scan_github_repos.py)
#   2. Logical repository checks (logical_repo_checks.py)
#   3. Agentic PR checks (agentic_pr_checker.py)
#   4. Labeling tool data synchronization (update_from_LT.py)
# - Add progress tracking and reporting
# - Implement resume capability for interrupted workflows
#
# TASK 2: INCORPORATE REPOSITORY SCANNING AND SHEET TRANSFER
# ==========================================================
# - Integrate scan_github_repos.py into the main workflow
# - Implement automatic sheet transfer logic:
#   * If a repository is identified as Python majority but is in Java sheet → transfer to Python sheet
#   * If a repository is identified as Java majority but is in JS/TS sheet → transfer to Java sheet
#   * Apply similar logic for all language combinations
# - Add language detection validation before transfer
# - Implement duplicate detection across sheets
# - Add logging and audit trail for transfers
# - Ensure data integrity during transfers
#
# IMPLEMENTATION NOTES:
# - Each script should be modified to accept parameters for orchestration
# - Consider using a configuration file for workflow settings
# - Add proper logging and monitoring capabilities
# - Implement rollback mechanisms for failed transfers
# - Add validation to prevent data loss during transfers

import traceback
from src import scan_github_repos
from src import logical_repo_checks
from src import agentic_pr_checker

def run_step(step_name, function_to_run):
    """Helper function to run a step of the workflow."""
    print(f"\n{'='*20}\n▶️  Starting: {step_name}\n{'='*20}")
    try:
        function_to_run()
        print(f"✅ Completed: {step_name}")
        return True
    except Exception as e:
        print(f"❌ FAILED: {step_name}")
        print(f"Error: {e}")
        traceback.print_exc()
        return False

def main_workflow():
    """
    Main workflow to orchestrate the repository evaluation process.
    1. Scans for new repos and adds them to the sheet.
    2. Runs logical checks on the repos in the sheet.
    3. Runs agentic PR checks on the logically-vetted repos.
    """
    print("🚀 --- Kicking off the main repository evaluation workflow --- 🚀")

    # if not run_step("Step 1: Scan for new GitHub repositories", scan_github_repos.main):
    #     print("\nWorkflow stopped due to failure in Step 1.")
    #     return

    if not run_step("Step 2: Run logical repository checks", logical_repo_checks.main):
        print("\nWorkflow stopped due to failure in Step 2.")
        return

    if not run_step("Step 3: Run agentic PR checks", agentic_pr_checker.main):
        print("\nWorkflow stopped due to failure in Step 3.")
        return

    print("\n🎉 --- Main repository evaluation workflow finished successfully! --- 🎉")

if __name__ == "__main__":
    main_workflow()

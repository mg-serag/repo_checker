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

# Differences: `agentic_pr_checker_clean.py` vs `get_relevant_prs_from_repo.py`

This document summarizes the key differences between the two scripts, with code snippets and explanations for each logical check.

---

## 1. **How PRs Are Fetched and Iterated**

### **agentic_pr_checker_clean.py**
- Uses REST API to fetch merged PRs after a certain date.
- Iterates through all PRs, applies logical checks, and collects results for reporting and sheet updates.

### **get_relevant_prs_from_repo.py**
- Uses GraphQL to fetch PRs, including files and closing issues, in batches.
- Iterates through PRs, applies logical checks, and saves relevant PRs to a database.

---

## 2. **Linked Issue Extraction**

### **agentic_pr_checker_clean.py**
```python
# Uses GitHub API timeline endpoint, falls back to body parsing
issue_number = get_closing_issue_number(pr_number, owner, repo, pr.get('body'))
```
- Tries to get the closing issue from the timeline API (cross-referenced closed issues).
- If not found, falls back to regex parsing of the PR body.

### **get_relevant_prs_from_repo.py**
```python
# Uses GraphQL closingIssuesReferences field
graphql_query = ...
pr_nodes = repo_data.get('pullRequests', {}).get('nodes', [])
for pr in pr_nodes:
    issue_nodes = pr.get("closingIssuesReferences", {}).get("nodes", [])
    if not issue_nodes:
        continue  # skip PRs with no linked issue
    issue_data = issue_nodes[0]
    issue_number = issue_data["number"]
```
- Uses the GraphQL `closingIssuesReferences` field, which is the most reliable way to get closing issues.
- Skips PRs with no linked issue.

**Difference:**
- `get_relevant_prs_from_repo.py` is more robust and direct for linked issues, while `agentic_pr_checker_clean.py` uses a REST API fallback and regex, which can be less reliable.

---

## 3. **Test File and Source File Checks**

### **agentic_pr_checker_clean.py**
```python
# Uses config-driven extension sets and test file detection
test_files = []
non_test_source_files = []
for fn in filenames:
    ext = os.path.splitext(fn)[1].lower()
    if ext not in allowed_ext:
        continue
    if os.path.basename(fn) in dependency_files:
        continue
    if _is_test_file(fn, LANGUAGE):
        test_files.append(fn)
    else:
        non_test_source_files.append(fn)
if len(test_files) < 1:
    return None, f"Only {len(test_files)} test file(s) found; at least 1 required."
if len(non_test_source_files) < 1:
    return None, f"Only {len(non_test_source_files)} non-test source file(s) found; at least 1 required."
```
- Requires at least 1 test file and 1 non-test source file (configurable).
- Uses config-driven extension sets for language families.

### **get_relevant_prs_from_repo.py**
```python
test_files = [f for f in files if is_test_file_path(f, language_config) and not is_asset_file_path(f, language_config)]
if len(test_files) < min_test_files:
    continue  # skip PRs with too few test files
```
- Requires at least 1 test file (configurable).
- Uses utility functions and language config for test/asset file detection.
- No explicit check for number of non-test source files.

**Difference:**
- `agentic_pr_checker_clean.py` enforces both test and non-test file minimums; `get_relevant_prs_from_repo.py` only enforces test file minimum.

---

## 4. **Non-Test Code Change Threshold**

### **agentic_pr_checker_clean.py**
```python
non_test_code_changes = 0
for file_info in files:
    filename = file_info.get('filename', '')
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_ext or os.path.basename(filename) in dependency_files:
        continue
    if _is_test_file(filename, LANGUAGE):
        continue
    additions = file_info.get('additions', 0)
    deletions = file_info.get('deletions', 0)
    non_test_code_changes += additions + deletions
if non_test_code_changes < 20:
    # reject
```
- Requires at least 20 lines of changes in non-test code files.

### **get_relevant_prs_from_repo.py**
```python
code_line_changes = 0
for file in pr.get('files', {}).get('nodes', []):
    if not is_test_file_path(file['path'], language_config):
        code_line_changes += file['additions'] + file['deletions']
if code_line_changes < MIN_PR_CODE_CHANGES:
    continue  # skip PRs with too few code changes
```
- Also requires at least 20 lines of changes in non-test code files.

**Difference:**
- Both scripts enforce this, but the file classification logic differs slightly (see above).

---

## 5. **Issue Body English Check**

### **agentic_pr_checker_clean.py**
```python
def is_english(text):
    if not text or not text.strip():
        return True
    total_chars = len(text)
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    return (ascii_chars / total_chars) >= 0.9
```
- Checks if at least 90% of the issue body is ASCII.

### **get_relevant_prs_from_repo.py**
```python
def is_english(text: str) -> bool:
    if not text:
        return False
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    return (ascii_chars / len(text)) >= 0.9
```
- Also checks for 90% ASCII, but returns False for empty text.

**Difference:**
- Minor: `agentic_pr_checker_clean.py` treats empty as English; the other treats empty as not English.

---

## 6. **LLM/Agentic Check**

### **agentic_pr_checker_clean.py**
```python
result, comment = run_llm_check(issue_body)
if not issue_body or len(issue_body.strip()) < 50:
    return "Bad PR", "Issue body is too short."
```
- Runs LLM check after logical checks, requires issue body to be at least 50 characters.

### **get_relevant_prs_from_repo.py**
```python
llm_result, llm_comment = safe_run_llm_check(issue_body)
if llm_result != "Good PR":
    continue  # skip PRs that fail LLM check
```
- Runs LLM check as part of logical checks, also requires minimum length.

**Difference:**
- Both use LLM, but `get_relevant_prs_from_repo.py` integrates it more tightly into the logical filtering.

---

## 7. **Other Notable Differences**
- **Database/Sheet Integration:**
  - `agentic_pr_checker_clean.py` updates Google Sheets and outputs CSVs.
  - `get_relevant_prs_from_repo.py` saves to a database and is more integrated with a backend system.
- **Manual/Debug Mode:**
  - `agentic_pr_checker_clean.py` now uses a manual mode for detailed reporting and repo selection.
  - `get_relevant_prs_from_repo.py` is designed for batch/automated backend use.

---

## **Summary Table**

| Check/Feature                | agentic_pr_checker_clean.py | get_relevant_prs_from_repo.py |
|-----------------------------|-----------------------------|-------------------------------|
| Linked Issue Extraction      | REST API + regex fallback   | GraphQL closingIssuesReferences|
| Test File Requirement        | 1+ test, 1+ non-test file   | 1+ test file only             |
| Non-Test Code Change Minimum | 20 lines                    | 20 lines                      |
| English Check                | 90% ASCII, empty=English    | 90% ASCII, empty=not English  |
| LLM/Agentic Check            | After logical checks        | Part of logical checks        |
| Output/Integration           | Google Sheets, CSV          | Database, backend             |
| Manual/Debug Mode            | Manual mode, detailed CSV   | Batch/automated, DB           |

--- 
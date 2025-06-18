# SWE Bench Tools – Repository Evaluation Workflow

This repository contains a multi-stage workflow that fetches candidate GitHub repositories, evaluates them against logical criteria, and performs a deeper PR-quality analysis with an LLM.

## Folder Overview

| Path | Purpose |
|------|---------|
| `scan_github_repos.py` | Fetches new GitHub repos (⭐ > 400) not yet listed in the Google Sheet and appends them to the first available empty rows. |
| `logical_repo_checks.py` | Performs fast logical checks (language %, stars, LOC, already-in-SWE-Bench check) and records results in the sheet. |
| `agentic_pr_checker.py` | Runs an LLM agent to identify at least **two** "Good PRs" for repos that passed logical checks. |
| `main.py` | Orchestrates the three steps above in sequence. |
| `creds.json` | Google Service-Account credentials ( **keep private!** ). |

## Google Sheet Layout

The workflow writes to the sheet with the following column mapping:

| Column | Meaning | Populated by |
|--------|---------|-------------|
| A | Date added | scan script |
| B | *(unused)* | — |
| C | `user/repo` | scan script |
| D | Repo URL | scan script |
| **E** | Logical check result (Yes/No) | logical checker |
| **F** | Total merged PRs | agentic checker |
| **G** | Logically relevant PRs | agentic checker |
| **H** | Agentic check passed (Yes if ≥ 2 good PRs) | agentic checker |
| I–K | *(reserved)* | — |
| **L** | Major language name | logical checker |
| **M** | Major language % | logical checker |
| **N** | Stars | logical checker |
| **O** | LOC | logical checker |
| **P** | Already in SWE Bench? | logical checker |

## Prerequisites

1. **Python 3.9+**
2. `pip install -r requirements.txt`
3. Environment variables:
   * `GITHUB_TOKEN` – personal-access token with `public_repo` scope.
   * *(optional for LLM)* `OPENAI_API_KEY`.
4. A Google Service Account JSON saved at `creds.json` **and** the sheet shared with the SA email.

## Running the Workflow

```bash
python main.py
```
The script will:
1. Add up to 5 000 new repos (subject to free rows) with ⭐ > 400.
2. Evaluate logical criteria and update columns E & L–P.
3. Run agentic PR analysis on repos with **E = Yes** and fill columns F–H.

## Running Individual Stages

```bash
python scan_github_repos.py            # only fetch & append repos
python -m repo_evaluator.logical_repo_checks   # only logical checks
python -m repo_evaluator.agentic_pr_checker    # only agentic checks
```

## How Each Stage Works

### 1. `scan_github_repos.py`

* **Goal** – keep the Google Sheet topped-up with new candidate repositories that have **≥ 400 GitHub stars**.
* **Process**
  1. Reads the sheet to determine how many empty rows remain.
  2. Builds star-range *slices* (`50k–100k`, `20k–49 999`, … `400–999`) because GitHub search only returns the first 1 000 hits per query.
  3. For each slice, issues a query `stars:<range> sort:updated-desc` and walks the paginated results.
  4. Skips repositories already present in Column C.
  5. Stops when either the sheet is full or `PULL_REPO_COUNT` (default 5 000) new repos have been collected.
* **Columns written** – A (Date), B (blank), C (`owner/repo`), D (repo URL).

### 2. `logical_repo_checks.py`

* **Goal** – quickly vet repos and decide if they are interesting for SWE-bench style tasks.
* **Row selection** – only rows where **Column M** (language %) is empty.
* **Checks performed**
  | Check | Pass condition | Notes |
  |-------|----------------|-------|
  | Already in SWE Bench? | No | Looks up a separate sheet of existing SWE-bench repos. |
  | Primary language share | ≥ 70 % | Based on GitHub Language API. |
  | Star count | ≥ 400 | Same threshold as fetch step. |
  | Lines-of-Code | `LOC ≥ max(0, 100 000 - (stars×200))` | Total LOC fetched via CodeTabs API. Skipped if language/stars already fail. |
* **Output**
  * **Column E** – "Yes" if **all** checks pass, otherwise "No".
  * **L–P** – language name, %, stars, LOC, and whether repo already existed in SWE-bench.

### 3. `agentic_pr_checker.py`

* **Goal** – make sure each logically-approved repo actually contains *Good PRs* suitable for automated patching.
* **Row selection** – rows where **E = Yes** **and** **H** is empty.
* **Pipeline**
  1. **Merged-PR harvest** – fetches closed PRs merged **after `MERGED_AFTER_DATE`** (config) via GitHub API.
  2. **Logical PR filter**  
     * PR body references a single issue (`closes #123`, etc.).
     * Files changed do **not** include disallowed languages (C/C++/Rust/…).
     * Contains at least one *test* file *and* at least one non-test source file.
     * Not purely dependency updates.
  3. **Agentic (LLM) check** – calls an OpenAI model with a prompt that classifies the linked issue as **"Good PR"** or **"Bad PR"**. Stops once **`TARGET_GOOD_PRS` (= 2)** good PRs are found.
* **Output columns**
  | Column | Meaning |
  |--------|---------|
  | F | Total merged PRs after Nov 2024 |
  | G | Logically relevant PRs that has an issue statement linked to it |
  | H | "Yes" if ≥ 2 Good PRs, else "No" |

## Customisation

* **Change fetch size** – edit `PULL_REPO_COUNT` in `scan_github_repos.py`.
* **Alter logical thresholds** – change star / LOC / language % constants inside `logical_repo_checks.py`.
* **Tune agentic behaviour** – adjust `TARGET_GOOD_PRS`, `MERGED_AFTER_DATE`, or the `AGENT_PROMPT` in `agentic_pr_checker.py`.

## Secrets & Private Files

`config.json` and `creds.json` **are intentionally excluded from version control** (listed in your `.gitignore`).

• **`config.json`** – JSON with a single key:

```json
{
  "GITHUB_TOKENS": "ghp_xxxxxxxxx ghp_yyyyyyyy"
}
```

Supply one or more space-separated personal-access tokens (PATs). These are rotated automatically to avoid hitting rate limits.  
If you prefer, you may instead set `GITHUB_TOKEN` in your environment; the first script will then ignore the config file.

• **`creds.json`** – Google *Service-Account* credentials used by all scripts to read/write the Google Sheet.  
Create a service account in Google Cloud Console, enable Drive & Sheets APIs, download the JSON key, rename/move it to this path, and **share the target sheet with the service-account email**.

Keep both files private – **never commit them**.
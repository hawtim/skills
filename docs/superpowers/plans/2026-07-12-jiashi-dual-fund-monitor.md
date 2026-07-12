# Jiashi Dual Fund Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and activate one tested skill that monitors the `000043` and `017730 A` fund portfolio through daily, weekly, and quarterly reports, then synchronizes generated reports to `hawtim/skills` through GitHub Connect.

**Architecture:** Keep deterministic portfolio reconstruction and rule evaluation in one standard-library Python module. Keep narrative rules, source guidance, scheduled prompts, and report layouts as progressively disclosed skill resources. Use three independent Codex cron automations with separate memory and idempotency rules.

**Tech Stack:** Python 3 standard library, `unittest`, Markdown, CSV, YAML metadata, Codex automations, GitHub Connect.

## Global Constraints

- Public artifacts contain only fund, trade, market, portfolio, and monitoring fields.
- Fixed target funds are `000043` and `017730` A; reject `017731` from the target portfolio.
- Initial plan is CNY 150,000 plus CNY 50,000; final caps are CNY 200,000 plus CNY 100,000.
- No automated trade execution; every suggested action requires human confirmation.
- Generated reports are written locally before any GitHub operation.
- Scheduled GitHub writes use GitHub Connect only and never fall back to `git push`.
- Preserve unrelated working-tree changes and commit only files within the new skill, its design/plan documents, and intentionally created automation metadata.

---

### Task 1: Establish an isolated implementation baseline

**Files:**
- Existing: repository worktree and Git metadata

**Interfaces:**
- Consumes: current repository HEAD containing the approved design
- Produces: isolated feature worktree or an explicitly verified safe in-place branch

- [ ] **Step 1: Detect repository isolation and branch state**

Run:

```bash
git rev-parse --git-dir
git rev-parse --git-common-dir
git rev-parse --show-superproject-working-tree
git branch --show-current
git status --short
```

Expected: a non-empty branch name and visibility into unrelated changes.

- [ ] **Step 2: Create or confirm an isolated workspace**

Follow `superpowers:using-git-worktrees`. If a new worktree is required, base it on the current HEAD so commit `29eb228` is included.

- [ ] **Step 3: Verify the baseline**

Run:

```bash
python3 -m unittest discover -s A-share -p 'test_*.py'
git status --short
```

Expected: existing tests pass, or no existing tests are discovered; the isolated workspace has no unexpected modifications.

### Task 2: Write failing portfolio-monitor tests

**Files:**
- Create: `A-share/jiashi-dual-fund-monitor/tests/test_portfolio_monitor.py`
- Create: `A-share/jiashi-dual-fund-monitor/tests/fixtures/empty-operation-log.csv`

**Interfaces:**
- Consumes: none
- Produces: expected interfaces `load_operations(path)`, `build_portfolio(operations, navs)`, and `evaluate_action(portfolio, checks)`

- [ ] **Step 1: Initialize the skill scaffold**

Run `skill-creator/scripts/init_skill.py` with name `jiashi-dual-fund-monitor`, output path `A-share`, resources `scripts,references,assets`, and generated interface values. Rename the generated `assets` directory to `templates` because the resources are report templates rather than copied output assets.

- [ ] **Step 2: Add behavior-first tests**

Create `PortfolioMonitorTests` with these exact test methods and assertions:

- `test_empty_log_builds_empty_portfolio`: an empty row list and two current NAVs produce zero total shares/value/invested and CNY 300,000 remaining capacity.
- `test_single_purchase_reconstructs_cost_and_remaining_cap`: a CNY 50,000 purchase of `000043` with 10,000 confirmed shares and zero fee produces 10,000 shares, CNY 5 average cost, CNY 150,000 fund capacity, and CNY 250,000 combination capacity.
- `test_multiple_purchases_use_confirmed_shares_and_fees`: two `017730` purchases use the sum of confirmed shares and include both recorded fees in net invested cost.
- `test_redemption_tracks_realized_value_and_remaining_shares`: a partial redemption decreases shares, preserves remaining average-cost basis, and records confirmed redemption proceeds separately.
- `test_duplicate_record_id_is_rejected`: duplicate IDs raise `ValueError("duplicate record_id: trade-1")`.
- `test_non_target_share_class_is_rejected`: code `017731` and `017730` with share class `C` each raise `ValueError`.
- `test_observe_band_does_not_trigger_add`: a 6% cost drawdown returns action `观察` and zero permitted add amount.
- `test_first_add_band_requires_all_non_price_checks`: a 9% drawdown returns `加仓候选` only when strategy, fundamentals, overlap, manager, freshness, and capacity checks are all true; changing any one to false returns `暂停加仓`.
- `test_second_add_band_is_capped_by_remaining_capacity`: a 15% drawdown cannot suggest more than CNY 25,000 per fund or the remaining fund cap, whichever is lower.
- `test_missing_or_stale_nav_degrades_to_watch`: a missing NAV or NAV older than the declared freshness limit returns `观察`, no amount, and the relevant missing-input label.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
python3 -m unittest A-share/jiashi-dual-fund-monitor/tests/test_portfolio_monitor.py -v
```

Expected: FAIL because `portfolio_monitor` does not yet provide the required interfaces.

### Task 3: Implement deterministic portfolio reconstruction and rules

**Files:**
- Create: `A-share/jiashi-dual-fund-monitor/scripts/portfolio_monitor.py`
- Create: `A-share/jiashi-dual-fund-monitor/data/operation-log.csv`
- Modify: `A-share/jiashi-dual-fund-monitor/tests/test_portfolio_monitor.py`

**Interfaces:**
- Consumes: canonical operation CSV rows and a mapping of fund code to dated NAV
- Produces: serializable portfolio state and action evaluation

- [ ] **Step 1: Implement canonical parsing and validation**

Define `TARGETS` exactly as follows, then implement `load_operations(path: str | Path) -> list[dict[str, object]]` and `validate_operations(rows: list[dict[str, object]]) -> None`:

```python
TARGETS = {
    "000043": {"name": "嘉实美国成长股票（QDII）", "initial": 150000.0, "cap": 200000.0},
    "017730": {"name": "嘉实全球产业升级股票发起式（QDII）A", "initial": 50000.0, "cap": 100000.0},
}

```

Validate required columns, unique `record_id`, supported `side`, allowed codes, positive monetary/share values, and `share_class == "A"` for `017730`.

- [ ] **Step 2: Implement portfolio reconstruction**

Implement `build_portfolio(operations: list[dict[str, object]], navs: dict[str, dict[str, object]]) -> dict[str, object]`.

Use confirmed shares and actual fees. Return per-fund shares, net invested cost, average cost per share, market value, unrealized result, realized proceeds, current weight, remaining cap, and combination totals. Empty logs return zero state without inventing positions.

- [ ] **Step 3: Implement rule evaluation**

Implement `evaluate_action(portfolio: dict[str, object], checks: dict[str, object]) -> dict[str, object]`.

Return one of `无动作`, `观察`, `加仓候选`, `暂停加仓`, `再平衡复核`, or `减仓/替换复核`, plus rule IDs, maximum permitted amounts, missing inputs, and `requires_human_confirmation=True`.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
python3 -m unittest A-share/jiashi-dual-fund-monitor/tests/test_portfolio_monitor.py -v
```

Expected: all portfolio tests PASS.

### Task 4: Author the skill resources and report contracts

**Files:**
- Modify: `A-share/jiashi-dual-fund-monitor/SKILL.md`
- Modify: `A-share/jiashi-dual-fund-monitor/agents/openai.yaml`
- Create: `A-share/jiashi-dual-fund-monitor/references/monitoring-rules.md`
- Create: `A-share/jiashi-dual-fund-monitor/references/data-sources.md`
- Create: `A-share/jiashi-dual-fund-monitor/references/scheduled-prompts.md`
- Create: `A-share/jiashi-dual-fund-monitor/templates/daily-report.md`
- Create: `A-share/jiashi-dual-fund-monitor/templates/weekly-report.md`
- Create: `A-share/jiashi-dual-fund-monitor/templates/quarterly-report.md`

**Interfaces:**
- Consumes: approved design and script output schema
- Produces: explicit skill workflow and exact report/automation contracts

- [ ] **Step 1: Write the controlling rule reference**

Include fixed targets, caps, initial build, two add bands, strategy/fundamental/portfolio gates, pause/review rules, scoring, and the human-confirmation boundary. Use rule IDs so script results and prose reports can cite the same rules.

- [ ] **Step 2: Write source and freshness guidance**

Define official-source priority, QDII NAV lag handling, IWF and semiconductor/technology proxy limitations, as-of labeling, and data-degradation behavior.

- [ ] **Step 3: Write three complete templates**

Every template must include title, data time, answer-first conclusion, facts versus judgment, rule checks, next trigger, missing data, and human confirmation. Daily, weekly, and quarterly templates add their cadence-specific sections.

- [ ] **Step 4: Write scheduled prompts**

Specify local report paths, duplicate handling, separate memory, GitHub Connect-only synchronization, commit naming, and failure reporting. The quarterly prompt must process a disclosure period once and skip when no new report exists.

- [ ] **Step 5: Write concise SKILL.md and regenerate openai.yaml**

Use an explicit-only trigger description for `$jiashi-dual-fund-monitor`, load the controlling references, route by daily/weekly/quarterly/manual mode, invoke the deterministic script when transaction data is used, and prohibit unconfirmed transactions.

### Task 5: Validate skill behavior and public output boundaries

**Files:**
- Create: `A-share/jiashi-dual-fund-monitor/tests/test_skill_contract.py`

**Interfaces:**
- Consumes: complete skill directory
- Produces: deterministic contract and privacy checks

- [ ] **Step 1: Write and run contract tests**

Test allowed target codes, required report headings, schedule strings, GitHub Connect-only language, no automatic trade action, and an allowlist for public CSV fields.

Run:

```bash
python3 -m unittest discover -s A-share/jiashi-dual-fund-monitor/tests -p 'test_*.py' -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run official skill validation**

Run:

```bash
python3 /Users/icemelon/.codex/skills/.system/skill-creator/scripts/quick_validate.py A-share/jiashi-dual-fund-monitor
```

Expected: validation succeeds.

- [ ] **Step 3: Run an empty-account forward simulation**

Run the portfolio script with the header-only operation log and dated sample NAVs. Expected: zero holdings, initial-build posture, no invented transaction, and explicit human confirmation.

- [ ] **Step 4: Inspect the complete diff**

Run:

```bash
git diff --check
git status --short
git diff -- A-share/jiashi-dual-fund-monitor
```

Expected: only intended new-skill changes in scope and no whitespace errors.

### Task 6: Commit and activate the three automations

**Files:**
- External Codex automation records for daily, weekly, and quarterly tasks

**Interfaces:**
- Consumes: `references/scheduled-prompts.md` and the local Codex project ID
- Produces: three enabled standalone local cron automations

- [ ] **Step 1: Commit the tested skill**

Stage only `A-share/jiashi-dual-fund-monitor/**` and the implementation plan. Commit message:

```text
Add Jiashi dual fund monitoring skill
```

- [ ] **Step 2: Resolve the Codex local project**

Use the Codex project-list tool and select `/Users/icemelon/Documents/invest/hawtim-skills`.

- [ ] **Step 3: Create the daily automation**

Create an enabled standalone local cron job at 08:30 Asia/Shanghai on weekdays. Name it `嘉实双基金每日监控`; its prompt uses the daily scheduled prompt and writes to `reports/daily`.

- [ ] **Step 4: Create the weekly automation**

Create an enabled standalone local cron job at 10:00 Asia/Shanghai on Saturdays. Name it `嘉实双基金每周监控`; its prompt writes to `reports/weekly`.

- [ ] **Step 5: Create the quarterly-disclosure automation**

Create an enabled standalone local cron job that checks once per week for newly published formal fund reports and emits at most one report per disclosure period. Name it `嘉实双基金季度监控`; its prompt writes to `reports/quarterly` and skips cleanly when nothing new exists.

- [ ] **Step 6: View and verify all three records**

Confirm status, project, prompts, timezone, schedules, report paths, separate memory expectations, and GitHub Connect-only synchronization.

### Task 7: Final verification and handoff

**Files:**
- All new skill files and Codex automation records

**Interfaces:**
- Consumes: committed implementation and live automation definitions
- Produces: verified handoff with paths, test evidence, commit SHA, and automation IDs

- [ ] **Step 1: Re-run the complete verification suite**

Run all unit tests, official skill validation, empty-account simulation, `git diff --check`, and scoped git status checks.

- [ ] **Step 2: Confirm no unrelated files were committed**

Run:

```bash
git show --stat --oneline HEAD
git status --short
```

Expected: the commit contains only the new skill and plan; pre-existing unrelated changes remain untouched.

- [ ] **Step 3: Complete the development branch workflow**

Use `superpowers:finishing-a-development-branch`, report integration options without modifying unrelated branches, and provide the recommended next action.

---
name: aicode-init
description: "Initialize AI Coding Loop for current project — scan, generate rules files, and set up .ai assets"
---

# /aicode-init — Project Initialization

Initialize the current project with AI Coding Loop. Scans the project, detects
language/framework/code style/testing/resources, and generates all necessary
configuration files.

## Trigger

```
/aicode-init
```

## Execution

> **引擎路径**: 使用 `CURSOR_PLUGIN_ROOT_PLACEHOLDER` 定位插件安装目录。如果该变量未设置，
> 读取 `.cursor/aicode/plugin-root.txt` 获取插件实际路径，替换下面的 `CURSOR_PLUGIN_ROOT_PLACEHOLDER`。

### Step 1: Scan project

Run the scan engine to detect the project environment:

```bash
python CURSOR_PLUGIN_ROOT_PLACEHOLDER/engines/run.sh init --scan-only --format json
```

Or on Windows:
```bat
python CURSOR_PLUGIN_ROOT_PLACEHOLDER\engines\run.sh init --scan-only --format json
```

### Step 2: Read scan results

Parse the JSON output:
- `profile.language` / `profile.framework` → tech stack
- `profile.has_claude_md` → if `true`, warn user — merging strategy will be used
- `profile.missing_required` → if non-empty, inform user which plugins are missing
- `profile.has_claude_dir` / `profile.has_ai_dir` → existing AI config files
- `profile.git_branch` → current git branch
- `profile.existing_files` → which AI files already exist

Present a summary to the user IN CHINESE:
- Detected tech stack
- Existing AI files
- Files that will be generated

### Step 3: Generate files

If the user approves or `--auto-confirm` is set:

```bash
python CURSOR_PLUGIN_ROOT_PLACEHOLDER/engines/run.sh init --generate --auto-confirm --format json
```

### Step 4: Read generate results

Parse JSON:
- `files_created` → list of generated files
- `files_skipped` → files that already existed and were skipped
- `files_merged` → files where merge suggestions were generated
- `missing_optional` → optional capabilities not available
- `next_steps` → suggested next actions
- `total_duration_ms` → time taken

### Step 5: Report to user (CHINESE)

Present a clean summary:
```
AI Coding Loop Init Complete

Detected:
  - Language: {language}
  - Framework: {framework}
  - Testing: {test_framework}

Generated Files:
  - CLAUDE.md
  - .claude/rules/code-style.md
  - .claude/rules/testing.md
  - .claude/rules/safety.md
  - .claude/commands/aicode-spec.md
  - .claude/commands/aicode-plan.md
  - .claude/commands/aicode-verify.md
  - .claude/commands/aicode-review.md
  - .claude/commands/aicode-memory.md
  - .claude/aicode/project-map.md
  - .claude/aicode/style.md
  - .claude/aicode/workflow.md
  - .ai/memory.md

Next steps:
  1. Review CLAUDE.md for accuracy
  2. Run /aicode-calibrate to confirm inferred rules
```

## Guardrails

- NEVER overwrite an existing CLAUDE.md without warning the user first
- NEVER modify business code during init
- If a required plugin is missing, tell the user, do NOT silently install it
- Present all findings in Chinese

**Summary**: Adds a daily scheduled trigger to the auto-docs workflow, enabling it to run automatically at midnight UTC in addition to existing push and manual triggers.

**Files Changed**:
- `.github/workflows/auto-docs.yml` — Added `schedule` trigger with a daily cron expression

**Key Changes**:
- Added `schedule` event trigger with cron expression `0 0 * * *` to run the auto-docs workflow once per day at midnight UTC
- Workflow previously only triggered on pushes to `main`/`dfitch8899-docbot` branches and manual `workflow_dispatch` events

**Breaking Changes**: None.

**Testing Notes**: None evident.
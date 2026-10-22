# Copilot-local bridge smoke test

The `copilot-local` backend in `adapters/project_bridge.py` clones the repository into an isolated checkout.
It creates a task-specific branch and starts the installed Copilot CLI in that checkout.
After Copilot returns, the adapter checks for code changes, commits them, and runs `validate_checkout`.
Validation checks whitespace and rejects changes to protected runtime directories.
It then runs the configured `validation_commands` (currently `python -m unittest discover -s tests -v`).
The adapter confirms validation did not alter the checkout, then pushes the branch and creates a draft pull request.
The `copilot-github` backend instead dispatches to GitHub coding agent and tracks its normal pull request.
This document does not report a live connectivity smoke-test result.

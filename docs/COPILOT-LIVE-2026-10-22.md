# Live Copilot bridge test – 2026-10-22

The user authorized a real connectivity test after the provider simulations passed.
Two small documentation-only tasks were submitted through the actual
`adapters/project_bridge.py` adapter. Production queues were not read or modified;
receipts and checkouts were isolated under the Codex workspace. The test configuration
used `codex/hunyuan-response-validation` as its base branch so the unmerged bridge
implementation and its tests were available. The default configuration remains `main`.

## Local Copilot: passed through draft PR

The installed GitHub Copilot CLI reported version `1.0.100-1`.
The first invocation rejected `--trust-folder` combined with `--session-id` before
agent execution. The adapter now names a fresh prompt-mode session with `--name`
and obtains the actual session ID from JSONL output. The rejected attempt's receipt
was retained, and the corrected test used a new task rather than silently resetting
an interrupted receipt.

- Task: `BRIDGE-SMOKE-DB68D0125F76`.
- Actual session: `2f0bc2ab-75dd-4f91-b11f-600d8a076294`.
- Copilot created exactly one documentation file in the isolated checkout.
- Returned code passed local whitespace/protected-path checks and the configured
  unittest suite: 82 tests run, 80 passed, 2 environment-dependent skips.
- Validated head: `a8233d325f69a93af7204cf3a200f880b6cf488f`.
- Adapter pushed the test branch and created
  [draft PR #5](https://github.com/phenixdk2020/ai-game-studio/pull/5).
- Final receipt status: `AwaitingCodeReview`. No merge or installation update occurred.

This tests the real local Copilot provider, Git publishing and local validation.
The queue/worker round trip is covered separately by the isolated HTTP integration
test; the live test deliberately did not use production runtime folders.

## GitHub cloud agent: dispatch denied

`gh auth status` confirmed the intended account, and the repository API confirmed
write/admin access. Nevertheless, `gh agent-task create --repo ... --base ...
--from-file ...` returned `failed to create job: 403 Forbidden`. No test PR was
created by this dispatch. The adapter retained `NeedsInput` and did not retry it.
Its error now explicitly directs the operator to cloud-agent access, repository
policy and CLI authentication. The exact reason for the server's refusal was not
established; ordinary repository permissions do not prove cloud-agent access.

[GitHub's cloud-agent CLI documentation](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-from-cli)
describes availability on paid Copilot plans and repositories where the agent has
not been disabled. Verify that access for the signed-in account before retrying.

Regression validation after these fixes: 83 tests run, 81 passed, 2 skipped.

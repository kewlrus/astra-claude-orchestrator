# <Task ID> implementation report
STATUS: <ready_for_review | needs_permission | blocked | failed>
Workspace/baseline: <actual path and baseline>
Session ID / run directory: <CLI-observed ID and runner artifact path, if available>

## Changes
<Changed paths and behavior; separate pre-existing changes.>

## Verification evidence
<Each actual command, working directory, exit code, result and log location.>

## Remaining risks or decisions
<Missing checks, limitations, blockers; never claim acceptance.>

## Resume checkpoint
<Completed internal steps, unfinished work, last failure, exact next action.>

## Permission requests to Astra
<None, or each request's unique ID, exact command, absolute cwd, reason and
expected effects. Include the same requests in the structured permission_requests
array. Requests are not approvals; save the checkpoint and yield for a decision.>

---
# Astra-only review record
Spec compliance: <pass | changes requested | blocked, with evidence>
Code quality/security: <pass | changes requested | blocked, with evidence>
Independent verification: <actual commands or visual/runtime checks>
Routing evidence: <CLI/provider metadata; static_only | inference_verified | unverified, not a worker self-identification>
Decision: <accepted | changes requested | blocked>
Correction cycles: <count>
Integration status: <what is present in the dependent workspace>

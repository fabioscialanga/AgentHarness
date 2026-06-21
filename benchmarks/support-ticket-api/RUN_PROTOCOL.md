# A/B Run Protocol

## Goal
Run the same implementation challenge twice:
- Scenario A: no framework
- Scenario B: with AgentHarness

The purpose is to compare outcomes fairly.

## Core fairness rules
Keep these constant across both runs:
- same benchmark specification
- same model/agent
- same tool access
- same time budget
- same human intervention policy
- same evaluation scorecard

Do not improve the second run by quietly changing the brief.
Do not change the rubric after looking at results.

## Recommended setup
Create two fresh working directories:
- `baseline-no-framework/`
- `baseline-with-agentharness/`

Use the same initial benchmark spec from `SPEC.md` for both.

## Scenario A — no framework
Provide only:
- the benchmark specification
- minimal execution instructions
- the allowed tools/environment

Do not provide:
- AgentHarness project files
- policy files
- workflow templates
- checklists
- generated framework metadata

Suggested prompt shape:
- build the project from the benchmark specification
- include tests and run instructions
- follow reasonable engineering judgment

## Scenario B — with AgentHarness
Start from the same benchmark specification, then add AgentHarness structure.

Recommended steps:
1. bootstrap a new AgentHarness project
2. adapt `PROJECT.md` to the benchmark brief
3. encode the project in `project.yaml`
4. keep or refine generated policies, workflows, and checklists
5. run validation/generation
6. implement the project inside that framework context

The key rule is that the underlying product goal must remain the same as Scenario A.

## Timeboxing
Recommended:
- implementation window: 60 to 120 minutes each
- optional review/fix pass: 15 to 30 minutes each

Use the same time budget on both sides.

## Human intervention policy
Pick one policy before the test and keep it fixed:
- fully autonomous until completion
- one review checkpoint midway
- one final review/fix pass only

Do not rescue one scenario more than the other.

## Required evidence to collect
For each run, capture:
- final repository/files
- README
- test command and result
- any validation output
- notes on where the agent got stuck or drifted
- elapsed time
- number of manual corrections

## Evaluation sequence
After both runs finish:
1. run the project
2. run the tests
3. score both implementations with `SCORECARD.md`
4. write a short comparison note

## Comparison questions
Use these questions explicitly:
- Which version adhered better to the original brief?
- Which version required less human cleanup?
- Which version is easier to review and extend?
- Which version handled validation and business rules more reliably?
- Did AgentHarness improve outcomes enough to justify its extra structure?

## Failure interpretation
If the AgentHarness version is only slightly better but much heavier, that is a warning.
If the no-framework version is faster but messier, that is useful data.
If the framework version is clearly more reliable with acceptable overhead, that is a strong signal.

The benchmark is successful if it teaches the truth, not if it flatters the framework.

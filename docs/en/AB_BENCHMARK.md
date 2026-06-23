# A/B Benchmark: with AgentHarness vs without a framework

## Why this exists
If AgentHarness is meant to be a serious framework, it should survive a simple but demanding test:

same project,
same initial specification,
same agent,
two different modes:
- without a framework
- with AgentHarness

This benchmark is meant to show whether the framework creates a real operational improvement or only adds more structure.

## What the benchmark pack contains
The practical benchmark lives in:
- `benchmarks/support-ticket-api/SPEC.md`
- `benchmarks/support-ticket-api/RUN_PROTOCOL.md`
- `benchmarks/support-ticket-api/SCORECARD.md`

Before running any benchmark campaign, freeze the design in:
- `benchmarks/PREREGISTRATION.md`

No benchmark run should start before that document is approved.

## Selected test case
The chosen project is a small internal support-ticket API.

Why this is a good test:
- it is not trivial like a toy app
- it is small enough to complete in a focused session
- it is rich enough to expose differences in:
  - clarity
  - validation
  - testing
  - business constraints
  - reviewability

## How to run the benchmark
### Scenario A, without a framework
Use only:
- the base project specification
- minimal instructions
- the same tools and environment

Do not use:
- `PROJECT.md`
- `project.yaml`
- policies
- workflow templates
- checklists
- `.framework` outputs

### Scenario B, with AgentHarness
Use the same base specification, but run it inside the AgentHarness flow:
- bootstrap the project
- adapt `PROJECT.md`
- update `project.yaml`
- use policies/workflows/checklists
- run validate/generate
- implement inside the framework context

## Fairness rules
To avoid bias, keep these constant:
- same specification
- same model/agent
- same time budget
- same human intervention policy
- same final scorecard

## What to measure
The most important metrics are not just speed or amount of code.

Focus on:
- functional completeness
- adherence to constraints
- validation quality
- test discipline
- architectural clarity
- human review burden
- amount of manual cleanup required

## How to interpret the result
The benchmark does not exist to prove that AgentHarness always wins.
It exists to answer this question honestly:

"Does the framework improve the outcome enough to justify its added structure?"

If yes, the framework has substance.
If no, it should be simplified.

## Success criterion
The AgentHarness version should ideally be:
- more consistent
- more verifiable
- more aligned with constraints
- easier to review

It does not have to be faster in every case.
The value may come mostly from reducing chaos and rework.

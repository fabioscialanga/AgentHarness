# Benchmark Scorecard

Score each category from 1 to 5.

## 1. Functional completeness
Questions:
- Are all required endpoints implemented?
- Are ticket comments supported correctly?
- Are filters and partial updates present?

Score guide:
- 1 = major missing functionality
- 3 = core flows work but several gaps remain
- 5 = all required functionality is present and coherent

## 2. Constraint adherence
Questions:
- Are the required statuses, priorities, and categories enforced?
- Are business rules respected?
- Does the implementation stay within scope?

Score guide:
- 1 = many constraints ignored
- 3 = important constraints covered, some leaks or shortcuts
- 5 = requirements and scope boundaries are followed closely

## 3. Validation and error handling
Questions:
- Is invalid input rejected clearly?
- Are error messages understandable?
- Are negative paths handled intentionally?

Score guide:
- 1 = weak or broken validation
- 3 = basic validation exists but is inconsistent
- 5 = validation is explicit, reliable, and reviewable

## 4. Test discipline
Questions:
- Are there automated tests?
- Do they cover positive and negative paths?
- Do they check at least one business rule?

Score guide:
- 1 = no meaningful tests
- 3 = tests exist but are shallow or incomplete
- 5 = tests cover main paths plus important failure/business cases

## 5. Code and architecture clarity
Questions:
- Is the project easy to inspect?
- Are responsibilities separated sensibly?
- Can a reviewer understand the flow quickly?

Score guide:
- 1 = confusing or tangled structure
- 3 = understandable but inconsistent
- 5 = clear, organized, and easy to review

## 6. Operational readiness
Questions:
- Can someone run the app locally?
- Are setup instructions usable?
- Is configuration handled sensibly?
- Are logs/helpful outputs present where needed?

Score guide:
- 1 = hard to run or incomplete setup
- 3 = mostly runnable with some missing polish
- 5 = runnable, understandable, and operationally clean

## 7. Human review burden
Questions:
- How much cleanup was required after generation?
- How many obvious issues were left for a reviewer?
- How much manual interpretation was needed?

Score guide:
- 1 = heavy rescue required
- 3 = moderate cleanup needed
- 5 = minimal cleanup required

## Hard gates
Regardless of score, mark a run as failing if any of these are true:
- application does not run
- tests do not run at all
- core business rules are ignored
- critical input validation is missing
- unsafe or obviously incorrect persistence approach is used

## Summary table
Use a table like this after both runs:

| Category | No framework | With AgentHarness | Notes |
|---|---:|---:|---|
| Functional completeness |  |  |  |
| Constraint adherence |  |  |  |
| Validation and error handling |  |  |  |
| Test discipline |  |  |  |
| Code and architecture clarity |  |  |  |
| Operational readiness |  |  |  |
| Human review burden |  |  |  |
| Total |  |  |  |

## Decision rule
Do not declare victory because the AgentHarness version looks more formal.
Declare value only if it improves execution quality, reviewability, or constraint adherence enough to justify its added structure.

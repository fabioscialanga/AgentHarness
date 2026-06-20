# Delivery Model

## Autonomy model
The project uses a medium-autonomy model.

Agents may:
- inspect files
- propose scoped changes
- implement isolated features
- add or update tests
- run local checks

Agents may not independently:
- change authentication model
- weaken validation rules
- alter upload safety constraints
- remove audit coverage
- modify CI/release behavior without review

## Task classes

### Low risk
Examples:
- documentation updates
- local refactors without behavior change
- adding tests
- improving error messages

### Medium risk
Examples:
- new endpoint in an existing bounded flow
- validation rule change
- notification behavior update
- persistence query change

### High risk
Examples:
- auth changes
- upload handling changes
- audit model changes
- dependency changes
- CI pipeline changes

## Review policy
- Low risk: human review recommended
- Medium risk: human review required
- High risk: human review required with focused checklist

# CivicTrack Example Documentation

## 1. What the example is

CivicTrack is a fictional but realistic open source web API used to demonstrate how AgentHarness-style project definitions can be written.

It is not a production application. It is a worked example designed to show how a repository could encode:
- project intent
- technical constraints
- quality expectations
- security rules
- agent operating boundaries
- reusable workflows

## 2. Product summary

CivicTrack is a lightweight civic issue intake and tracking platform.

Its purpose is to help citizens and local operators handle reports such as:
- potholes
- broken street lights
- abandoned waste
- neighborhood maintenance issues

The V1 scope is intentionally narrow:
- receive reports
- validate them
- assign them
- track status changes
- maintain an audit trail
- optionally notify stakeholders

## 3. Problem it solves

Small municipalities and civic organizations often manage issue reports through email, spreadsheets, or informal messaging.

That creates:
- lost information
- unclear ownership
- poor accountability
- weak reporting
- inconsistent follow-up

CivicTrack is designed as a simple, self-hostable, auditable base for making that workflow visible and manageable.

## 4. Primary users

The example identifies four main user groups:
- citizens who submit reports
- municipal or civic operators who handle tickets
- area coordinators who assign and close work
- technical administrators who manage configuration and security

## 5. Key workflow

The canonical flow described in the example is:
1. A citizen submits a report with description, category, location, and optional photo.
2. The system validates minimum required fields.
3. The report enters the `new` state.
4. An operator assigns the issue to a team or owner.
5. The owner moves the issue through states such as `in_review`, `in_progress`, `resolved`, and `closed`.
6. The citizen receives status updates when a notification channel is available.
7. The system keeps an event history and audit trail.

## 6. Explicit non-goals for V1

The example deliberately excludes:
- advanced GIS
- AI-based routing
- ERP or municipal protocol integrations
- native mobile apps
- advanced analytics for large institutions

This is useful because it shows how scope boundaries should be encoded early.

## 7. Technical profile

The structured config describes a simple Python API stack:
- language: Python
- framework: FastAPI
- database: PostgreSQL
- package manager: uv
- ORM: SQLModel
- API style: REST

The defined modules are:
- api
- domain
- validation
- notifications
- persistence
- audit

Optional external services are:
- SMTP
- webhooks

## 8. Governance model

The example uses a medium-autonomy model.

Agents may:
- inspect files
- propose scoped changes
- implement isolated features
- add or update tests
- run local checks

Agents may not independently:
- change authentication behavior
- weaken validation rules
- alter upload safety constraints
- remove audit coverage
- modify CI or release behavior without review

Human review is explicitly required for higher-risk areas such as:
- auth changes
- dependency changes
- CI pipeline changes
- upload handling changes
- audit model changes

## 9. Quality expectations

The example makes quality gates first-class.

Required checks include:
- formatting
- linting
- type checking
- unit tests
- no hardcoded secrets

Bug fixes are expected to leave a regression test when technically feasible.

The definition of done also requires:
- bounded scope
- updated tests where relevant
- edge-case consideration
- respect for review requirements
- an execution summary

## 10. Security posture

The example encodes a medium security level and assumes personally identifiable information may be present.

Important constraints include:
- secrets must come from environment variables
- uploaded files must be validated
- dependency changes must be controlled
- input validation is mandatory
- logging must be safe with respect to personal data

This is useful because it demonstrates that security policy belongs in the project definition, not only in later implementation notes.

## 11. Why this example matters for AgentHarness

CivicTrack matters because it turns an abstract framework idea into a concrete repository shape.

It demonstrates how a project can express:
- human-readable purpose
- machine-readable constraints
- operational instructions for agents
- checklists for humans and machines
- autonomy and review boundaries

Without an example like this, AgentHarness would remain too conceptual.

## 12. Files worth reading first

To understand the example quickly, start with:
- `examples/civictrack/PROJECT.md`
- `examples/civictrack/project.yaml`
- `examples/civictrack/AGENTS.md`
- `examples/civictrack/docs/ARCHITECTURE_SUMMARY.md`
- `examples/civictrack/docs/DELIVERY_MODEL.md`

## 13. One-sentence summary

CivicTrack is the first worked example showing how AgentHarness can encode project intent, governance, and engineering workflows in a reusable structure.

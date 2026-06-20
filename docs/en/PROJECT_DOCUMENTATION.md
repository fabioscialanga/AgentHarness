# AgentHarness Project Documentation

## 1. Purpose

AgentHarness is a framework concept for converting project intent into controlled agent execution.

Its objective is not to create another coding assistant. Its objective is to provide the operating layer around AI agents so engineering teams can work with them under explicit constraints, review boundaries, and verification rules.

In short:
- project intent goes in
- operating context is generated
- agents work inside bounded rules
- outputs are checked against quality and security expectations

## 2. The problem it tries to solve

Many teams experimenting with AI-assisted development make the same mistake: they focus on the model and underinvest in the operating system around the model.

Typical failure modes are:
- vague project context
- inconsistent instructions across tasks
- unclear autonomy limits
- weak testing discipline
- poor security controls
- no explicit review gates
- no reusable operating templates

AgentHarness addresses this by making the project itself more machine-operable without losing human control.

## 3. Core thesis

A capable model alone is not enough for reliable software delivery.

What matters is the harness around the model:
- structured context
- allowed tools
- forbidden actions
- workflow templates
- quality gates
- review checkpoints
- traceable project rules

AgentHarness focuses on formalizing that harness.

## 4. What AgentHarness is

AgentHarness is intended to be:
- a project-definition layer for AI-assisted engineering
- a bootstrap system for reusable agent context
- a repository of project rules and execution constraints
- a way to standardize recurring engineering workflows
- a bridge between human intent and bounded agent execution

## 5. What AgentHarness is not

AgentHarness is not:
- a model provider
- a replacement for engineering judgment
- a guarantee of correctness
- only a prompt library
- only a scaffolding generator
- a fully autonomous software factory

The design assumes human review remains necessary for important changes.

## 6. Operating model

The operating model starts from explicit project artifacts and turns them into execution guidance for agents.

Typical flow:
1. A team defines the project in human-readable form.
2. The project is also captured in structured machine-readable form.
3. Governance files define autonomy, review, security, and testing rules.
4. Workflow templates define how common tasks should be executed.
5. Agents operate inside those constraints.
6. Humans review work according to the declared risk level.

## 7. Main repository building blocks

### `PROJECT.md`
Human-readable project intent.

It explains:
- the product goal
- users
- use cases
- scope boundaries
- technical constraints
- business constraints
- risks
- team conventions

### `project.yaml`
Machine-readable project definition.

It captures structured information such as:
- project type
- stack
- modules
- external services
- testing requirements
- quality gates
- security rules
- agent policy
- generated deliverables

### `AGENTS.md`
Rules for agents operating inside the repository.

Typical content includes:
- coding boundaries
- risk limits
- human-review areas
- required validation behavior
- minimum completion criteria

### `workflows/`
Reusable task templates for recurring engineering work.

Examples:
- create a feature
- fix a bug
- refactor a module
- add tests

### `checklists/`
Human- and agent-readable completion criteria.

Examples:
- definition of done
- testing standards
- security review
- AI code review checklist

### `policies/`
Machine-oriented governance files.

They define constraints such as:
- autonomy levels
- mandatory checks
- secrets handling
- dependency rules
- review requirements

### `.framework/`
Reserved area for generated metadata and framework outputs.

Examples could include:
- normalized project data
- risk matrices
- dependency maps
- generated task inputs
- verification summaries

## 8. Repository structure

Current repository structure:
- `README.md` — top-level overview
- `docs/en/` — English documentation
- `docs/it/` — Italian documentation
- `examples/civictrack/` — worked example showing the framework style

Inside `examples/civictrack/`:
- `PROJECT.md`
- `project.yaml`
- `AGENTS.md`
- `docs/`
- `workflows/`
- `checklists/`
- `policies/`
- `tests/`
- `.framework/`

## 9. The CivicTrack example

The first example in this repository is CivicTrack, a fictional but credible open source civic issue tracking API.

It exists to demonstrate how AgentHarness inputs and policies can be shaped in practice.

CivicTrack shows:
- how a project brief can be written
- how structured config can encode stack and constraints
- how agent rules can be made explicit
- how task workflows can be standardized
- how testing and security can be represented from day one

This is intentionally an example project, not a production product.

## 10. Current maturity level

This repository is in bootstrap phase.

That means:
- the conceptual direction is defined
- the initial repository shape exists
- one worked example is present
- the actual framework engine is not built yet

This is an important strength and an important limitation.

Strength:
- the repository already expresses a coherent philosophy
- the example makes the idea concrete

Limitation:
- there is not yet a validator, generator, CLI, or execution runtime
- much of the value is still encoded as documentation and project structure

## 11. Near-term roadmap

Recommended next steps:
1. Define the canonical schema for `project.yaml`.
2. Add validation rules and schema checks.
3. Define the generation contract for framework outputs.
4. Decide which artifacts are authored manually vs generated automatically.
5. Add a small validator or bootstrap CLI.
6. Add more examples with different risk profiles.
7. Prove that the framework improves consistency, not just documentation quality.

## 12. Who this is for

AgentHarness is most relevant for:
- engineering teams adopting AI-assisted development
- organizations that need stronger governance around agents
- teams that want repeatable workflows rather than ad hoc prompting
- projects where testing, security, and review discipline matter

It is less useful for:
- one-off throwaway prototypes
- teams unwilling to maintain project metadata
- environments where no review model exists

## 13. Design principles

The repository currently expresses these principles:
- explicit beats implicit
- constraints are part of enablement, not friction
- testing and security belong in the operating model
- autonomy must be bounded by risk
- examples should be concrete enough to be reusable
- human review remains necessary for meaningful risk

## 14. Practical value proposition

If developed well, AgentHarness could help companies:
- reduce ambiguity in AI-assisted tasks
- make agent behavior more predictable
- improve consistency across engineering work
- lower the chance of unsafe or low-quality changes
- move from prompt improvisation toward governed execution

## 15. Current limits and open questions

Important unresolved questions include:
- What is the minimum schema that remains useful?
- Which outputs should be generated automatically?
- How strict should policy enforcement be?
- How will agents consume these files in practice?
- How will verification be standardized across stacks?
- How will the framework avoid becoming documentation overhead?

These are not flaws to hide. They are the real product questions to answer next.

## 16. One-sentence summary

AgentHarness is an attempt to turn project specification into bounded, reviewable, and repeatable agent execution.

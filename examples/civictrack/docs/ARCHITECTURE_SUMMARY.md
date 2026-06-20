# Architecture Summary

## Overview
CivicTrack is a lightweight API-centric platform for civic issue intake and tracking.

The V1 is intentionally narrow:
- receive reports
- validate required fields
- assign and track status
- keep audit trail
- optionally notify stakeholders

## Main components

### 1. API
Responsibilities:
- expose REST endpoints
- validate request shape at transport level
- map HTTP requests to domain services

### 2. Domain
Responsibilities:
- manage issue lifecycle
- enforce valid state transitions
- apply business rules
- coordinate audit event generation

### 3. Validation
Responsibilities:
- field-level validation
- category/state constraints
- upload metadata validation

### 4. Persistence
Responsibilities:
- store issues, users, assignments, events
- abstract database access
- avoid embedding business decisions

### 5. Notifications
Responsibilities:
- send optional email or webhook notifications
- isolate integration failures from core issue lifecycle

### 6. Audit
Responsibilities:
- register meaningful events
- record actor, timestamp, and action
- support later operational review

## Key design choices
- API first, no heavy UI assumption in V1
- self-hostable stack
- minimal but explicit modularity
- testability and auditability prioritized over feature breadth

## High-risk areas
- status transition correctness
- upload validation
- logging of personal data
- silent notification failures
- regressions in audit event creation

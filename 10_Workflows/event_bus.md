# Event Bus Architecture

**Document ID:** WF-002  
**Version:** 1.0  
**Status:** Locked  

---

## 1. Purpose
Athena OS uses an event-driven architecture (CQRS). Services do not call each other directly in a linear chain. Instead, they listen to an **Event Bus** for facts that have occurred, and they issue **Commands** when they need an action performed. This drastically improves scalability and automation.

## 2. Event vs. Command

- **Event (`event.schema.json`):** A fact that happened in the past. It cannot be rejected or changed. (e.g., `ChapterWritten`).
- **Command (`command.schema.json`):** An imperative request for a service to do something. It can be rejected. (e.g., `WriteChapter`).

## 3. The Core Event Flow

When a project is initiated, the Athena Runtime orchestrates the pipeline by passing messages through the Event Bus. The standard flow for a chapter is as follows:

1. `StoryCreated` (Event published by CEO)
2. `OutlineRequested` (Command sent to Story Architecture Service)
3. `OutlineCompleted` (Event published by Story Architecture)
4. `CharacterPlanningStarted` (Event)
5. `CharacterPlanningCompleted` (Event)
6. `WorldPlanningStarted` (Event)
7. `ResearchStarted` (Event)
8. `ResearchCompleted` (Event)
9. `WriteChapter` (Command sent to Literary Service)
10. `DraftStarted` (Event published by Literary Service)
11. `DraftCompleted` (Event published by Literary Service)
12. `RunQACheck` (Command sent to QA Service)
13. `QAStarted` (Event)
14. `QACompleted` (Event - contains pass/fail status)
15. `ChapterApproved` (Event - if QA passed) or `ChapterRejected` (Event - if QA failed, looping back to step 9)

## 4. The Pub/Sub Model
Because services subscribe to events, multiple actions can happen asynchronously. 
- When `DraftCompleted` is published, the **Continuity Service** might update the Story Bible in the background while the **QA Service** begins running the readability logic.
- No service is bottlenecked waiting for a synchronous API response from another agent.

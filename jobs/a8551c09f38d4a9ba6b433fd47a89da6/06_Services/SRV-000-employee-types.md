# EMP-000: Employee Types & Context Loading

**Document ID:** EMP-000  
**Version:** 1.0  
**Status:** Locked  

---

## 1. Purpose
With over 220 distinct roles mapped in ORG-003, Athena Publishing OS cannot load every employee into active memory for every project. This document defines the technical mechanism for managing context windows by dividing employees into two strict categories: **Permanent Employees** and **Contract Specialists**.

## 2. Permanent Employees (Core Framework)

**Definition:** Roles that exist in every single project, regardless of genre, scope, or subject matter. They form the skeleton of the company.

**Characteristics:**
- Loaded into active project memory (MEM-001) by default.
- They manage structure, workflows, objective quality, and core execution.
- They have authority to approve or reject standard pipeline transitions.

**Examples:**
- Chief Executive Officer (EMP-001)
- Literary Architect (EMP-002)
- Story Director
- Developmental Editor
- Copy Editor
- Timeline Manager

## 3. Contract Specialists (Dynamic Experts)

**Definition:** Highly specialized domain experts (e.g., subject matter experts, genre-specific writers, esoteric consultants) whose expertise is only required for specific tasks or specific types of books.

**Characteristics:**
- *Not* loaded into active memory by default. They exist in cold storage (the `06_Employees` archive).
- Dynamically summoned (loaded) *only* when their specific expertise is required by the prompt.
- They act as consultants. They provide data, specific critiques, or specialized prose, but they rarely hold final Approval authority over a macro-pipeline phase.

**Examples:**
- Military Strategist (Only summoned for war scenes or military fiction).
- Shakespearean Stylist (Only summoned for high-fantasy dialogue).
- Medical Researcher (Only summoned for medical thrillers or specific injury scenes).
- Romance Specialist (Only summoned when romantic subplots are active).

## 4. The Summoning Protocol

When the workflow dictates the need for a Contract Specialist, the following protocol executes:

1. **Identification:** The active Permanent Employee (e.g., the Literary Architect) identifies a knowledge gap (e.g., "I need to know how a 19th-century galleon maneuvers").
2. **Requisition:** A structured report (COM-001) is issued to the Project Coordinator requesting the specific Contract Specialist (e.g., *Naval Historian*).
3. **Context Injection:** The Automation Division (AUTO-001) spins up the Contract Specialist, injecting *only* the relevant sub-context (not the entire Project Bible) into their prompt window.
4. **Execution & Dismissal:** The Specialist completes the micro-task, passes the data back to the Permanent Employee, and is dismissed from active memory, freeing up tokens.

## 5. Architectural Benefit
This division ensures Athena remains incredibly lean and cost-efficient during operation, while retaining the capability to assemble world-class expert teams for any conceivable subject matter.

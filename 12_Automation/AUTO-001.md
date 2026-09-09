# AUTO-001: Prompt Generation Protocol

**Document ID:** AUTO-001  
**Version:** 1.0  
**Status:** Locked  

---

## 1. Purpose
Athena Publishing OS is an autonomous system. Human users do not manually write prompts for the Literary Author or the Dev Editor. The system itself generates the precise instructions required for sub-agents to execute their tasks. This document governs how those prompts are constructed.

## 2. Principle: Systems Before Prompts
A prompt is merely the final execution layer of the architecture. A prompt should never contain systemic logic; it should only contain execution context. The intelligence of Athena lies in the architecture, not in a "magic prompt."

## 3. Standard Prompt Structure (The Wrapper)
When Athena spins up a sub-agent to perform a task (e.g., draft a chapter), the prompt must be generated programmatically using the following wrapper:

### Block 1: Role Injection
*Loads the employee identity.*
`[Load: 06_Employees/EMP-005.md]`
"You are the Literary Author. Adopt the professional principles and methodologies defined in your specification."

### Block 2: Memory Loading
*Loads the necessary context.*
`[Load: MEM-001 Tier 1 (Constraints)]`
`[Load: MEM-001 Tier 2 (Previous Chapter Text)]`

### Block 3: The Task (The Payload)
*The specific action to be performed.*
"Execute Chapter 4 based on the following Beat Sheet: [Insert Beat Sheet segment]. Follow the aesthetic guidelines in PHIL-001."

### Block 4: Output Formatting
*How the output must be delivered.*
"Return the prose in standard markdown format. Do not include introductory conversational text. Do not output anything other than the chapter text."

## 4. Automation Scaling
As Athena grows, the Automation division is responsible for identifying repetitive manual tasks (e.g., formatting EPUBs, checking spelling) and replacing them with deterministic scripts or tightly constrained LLM prompts that require zero human intervention.

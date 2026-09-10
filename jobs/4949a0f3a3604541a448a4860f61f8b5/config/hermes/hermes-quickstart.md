# Hermes Quickstart Guide for AthenaOS

> **Running Hermes as an autonomous agent with file/terminal access instead of pasting into a chat UI?** This guide (and the manual per-phase copy/paste flow it describes) doesn't apply to you. Use `system-prompt.md` §6 and `agentic-operating-protocol.md` instead — they define autonomous, subagent-driven execution and explicitly forbid shortcutting into `athena.py`.


You have an incredibly powerful, 500-document publishing system on your hard drive. But local LLMs (like Hermes) can't read 500 documents at once. 

AthenaOS is designed to be a **"Context-Switched Workflow."** You are the CEO. You move Hermes from department to department by changing what context it has loaded.

Here is exactly how you use AthenaOS right now:

### Step 1: Set the Core Identity
Take the contents of `config/hermes/system-prompt.md` and set it as the core system prompt / custom instructions in your Hermes UI (LM Studio, Ollama, GPT4All, etc). Leave it there forever. This makes Hermes permanently understand it is "AthenaOS".

### Step 2: Start a New Project (The Architecture Phase)
Open a new chat in Hermes. You want to start outlining a book.
1. Open `06_Services/SRV-002.md` (Story Architect) in your text editor. Copy all the text.
2. Paste it into Hermes.
3. Tell Hermes: *"Initialize SRV-002. I want to write a sci-fi thriller about a detective on Mars. Ask me the questions you need to fill out the Pre-Writing Determination Protocol."*
4. Hermes will now act strictly as the Story Architect. Talk back and forth until you have a solid Outline. Save that outline to a file on your desktop.

### Step 3: Build the Characters
Clear the chat context (start a new chat so Hermes doesn't get confused by the old instructions).
1. Open `06_Services/SRV-003.md` (Character Psychologist). Copy the text.
2. Paste it into Hermes, along with the Outline you saved in Step 2.
3. Tell Hermes: *"Initialize SRV-003. Using the attached outline, run the Complete Character Excavation Protocol on my main character."*
4. Save the resulting psychological profile.

### Step 4: Write the Draft
Clear the chat. Start a new one.
1. Copy `06_Services/SRV-005.md` (Literary Author).
2. Paste it into Hermes, along with the Outline (Step 2) and the Character Profile (Step 3).
3. Tell Hermes: *"Initialize SRV-005. Write the prose for Chapter 1 based on the outline. Use the Sensory Writing Protocol."*

### The Secret to AthenaOS
The secret to using AthenaOS manually is **you never ask the AI to 'write a book'.** 

You treat Hermes like an employee who can only do one job at a time. When you want structural editing, you load the `SRV-007` instructions. When you want marketing copy, you load the `SRV-019` instructions. 

Use the `config/hermes/task-loader.md` document as your cheat sheet for which files to combine at which stages.

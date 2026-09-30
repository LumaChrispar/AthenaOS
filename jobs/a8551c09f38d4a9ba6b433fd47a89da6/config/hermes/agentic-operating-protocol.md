# Agentic Operating Protocol (Subagent Dispatch)

> **Historical protocol.** For autonomous manuscript jobs, follow
> `AUTONOMOUS_WORKER.md` at the repository root instead. Launch the durable Python
> worker; its job loop replaces the per-service dispatch and runtime prohibition
> below. Draft delivery does not require a human sign-off.

**Document ID:** HERMES-AOP-001
**Status:** Active — supersedes the manual copy/paste flow in `hermes-quickstart.md` and `task-loader.md` whenever you (Hermes) have file, terminal, or subagent-dispatch tools available.
**Read together with:** `system-prompt.md` §6, `06_Services/SRV-000-employee-types.md` (the Summoning Protocol this formalizes), `10_Workflows/WF-001.md`, `10_Workflows/states.md`, `config/workflow.yaml`, `config/quality.yaml`.

---

## 1. Why this file exists

`system-prompt.md` was originally written for a human pasting one `.md` file at a time into a chat window. That's not your situation anymore. You have the whole repository on disk and the ability to act. The old manual flow taught one bad habit that carries over if you're not careful: **treating `athena.py` as "the button that does the pipeline."** It isn't — it's a thin, low-fidelity stand-in someone wrote before the full SRV files existed in their current depth. This document replaces "run the script" with "be the orchestrator," using real subagent calls.

## 2. The core rule

**Every SRV-xxx invocation is a subagent dispatch, not a function call and not a persona you privately imagine yourself into.** When WF-001 or a SOP says "the Literary Architect does X," you spawn a subagent for that step. This matters for three concrete reasons:

- **Context isolation.** A subagent doing SRV-016 (Continuity Check) shouldn't be holding the accumulated bias of having just written the chapter itself — it should come at the manuscript cold, the way the SRV file's own Evaluation Framework assumes.
- **Fidelity.** The full SRV file (Identity, Core Philosophy, Protocols, Interface Contract) is the persona. Summarizing it into a one-line instruction — which is exactly what `orchestrator.py` does — throws away the reason it's a 26-service architecture instead of one big prompt.
- **Real parallelism.** WF-001 Stage 2 explicitly allows Architecture and Character Psychology to run concurrently. That's only real if they're actually separate subagent calls, not you sequentially role-playing both.

## 3. Dispatch procedure (per SRV call)

For every step in WF-001 / a SOP that names an acting service:

1. **Read the full file** at `06_Services/SRV-XXX*.md` (or `07_SOPs/SOP-XXX*.md` for a procedure). Do not summarize it before use — pass it whole.
2. **Gather the Interface Contract inputs.** Check `08_Memory/` for the required upstream artifacts (`outline.json`, `psychology.json`, `story_bible.json`, etc.). If a required input is missing, this is Directive 3 from `system-prompt.md` — halt this branch and either produce the missing dependency first (if it's upstream in WF-001) or escalate to the user (if it's something only they can supply, e.g. the original concept).
3. **Spawn the subagent** using your dispatch tool with:
   - `persona` = the full raw text of the SRV/SOP file (step 1)
   - `task` = the specific instruction for this call (what WF-001's stage description says to do)
   - `inputs` = the gathered artifacts (step 2), passed in full — not paraphrased
   - `expected_output` = the exact schema from the service's Interface Contract (check `08_Memory/schemas/` if referenced)
4. **Validate the output** against the Interface Contract before treating the step as done. If it doesn't conform, send it back to the same subagent with the specific mismatch — don't silently reshape it yourself, and don't fall back to writing it yourself either (that's you skipping the Service layer).
5. **Persist the artifact** to `08_Memory/` under the filename convention already used in `orchestrator.py` (e.g. `chapter_01.json`, `story_bible.json`) so state survives across turns/sessions, and update `08_Memory/pipeline_state.json` yourself if you want crash-recovery — this is the one legitimate reuse of the Python layer's *data conventions*, not its *execution*.
6. **Advance the state machine** per `states.md`. Never mark something `APPROVED` without it having actually passed through `IN_REVIEW`. If your dispatch tool doesn't enforce this for you, you enforce it by refusing to proceed to the next WF-001 stage until the gate condition is true.

## 4. Contract Specialists (dynamic subagents)

For the "Contract Specialist" tier from `SRV-000-employee-types.md` §3-4 (Naval Historian, Shakespearean Stylist, etc.): the Summoning Protocol described there **is** a subagent dispatch — just an ad hoc one. When a Permanent Employee subagent's output flags a knowledge gap, you dispatch a specialist subagent with only the relevant slice of context (per §3 of that file: "not the entire Project Bible"), fold their output back into the calling subagent's next turn, and don't keep them resident.

## 5. What you never do in this mode

- Never run `python athena.py ...` or call into `orchestrator.py` to generate, edit, or judge creative content. If you catch yourself about to do this because it's faster, that's the signal to stop — speed is not the goal here; fidelity to the SOPs is.
- Never collapse two distinct SRV roles into a single subagent call "to save a turn." If WF-001 lists them as separate acting services, they're separate dispatches.
- Never wait for the user to say "take charge," "go ahead," or "continue" between WF-001 stages. Per `system-prompt.md` §6.2, that's the default. Only stop at a real escalation, gate failure past `max_revision_loops`, or Stage 6 sign-off.
- Never treat "no constraints" as license to skip `IN_REVIEW` or the `quality.yaml` thresholds. Those aren't constraints on you — they're the product. A publishing OS that skips its own QA gate isn't autonomous, it's just fast and wrong.

## 6. If your dispatch tool can't actually spawn isolated subagents

If your framework only gives you a single context (no real subagent primitive yet), simulate isolation as closely as possible: explicitly clear/reset your working notes between role-switches, re-read the SRV file fresh each time rather than relying on memory of it from earlier in the session, and never let one role's draft silently bias the next role's "independent" review. This is weaker than real dispatch but strictly better than the current failure mode of skipping straight to `athena.py`.

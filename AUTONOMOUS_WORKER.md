# Athena autonomous manuscript worker

Status: working prototype, verified with simulated model responses. Live prose
quality, provider availability, elapsed time, and monetary cost have not been
benchmarked. This runtime delivers a Markdown draft; it does not publish books.

## Run a book

### Local web interface

```powershell
python athena.py ui
```

Open **http://127.0.0.1:8765**. Open **Settings** in the sidebar, select Ollama
or LM Studio, use **Find models**, choose your model, and **Save settings**.
Return to **New conversation**, describe your story, and send your first message.
Settings has its own address at **http://127.0.0.1:8765/settings**.
It also controls maximum requests per book, output tokens per response, and
response timeout. These UI defaults are stored in `config/ui_settings.json`
and applied to new UI jobs; existing jobs retain their original configuration.
CLI jobs continue to use `config/models.yaml` and explicit CLI overrides.
The sidebar lists your books; each book shows saved progress, usage, errors,
and an activity log. Completed books can be read or downloaded as Markdown.
No Node.js build or additional web framework is needed.

### Conversations

The home screen is a message composer: describe your book and optionally set a
chapter count before sending. Each book opens as a conversation at `/books/JOB_ID`.
The original brief appears as your first message. Writing activity is translated
from actual worker logs and saved state into readable updates; the original log
remains under **Technical details**. These updates do not consume model requests.

The follow-up composer sends questions to the book's selected model, with the
saved brief, outline, world information, and recent conversation as context.
Replies are stored in `jobs/JOB_ID/conversation.json`. This is a discussion:
suggested revisions are not automatically applied to the manuscript. Follow-up
requests may incur provider charges, and use a separate `chat_usage.json` ledger,
capped at the smaller of 50 requests or the job's configured request limit, with
up to 2,048 output tokens per response. Book generation keeps its own budget.
No real model requests are made by the automated conversation tests.

For **LM Studio**, load a model and start its server in the Developer tab.
The default endpoint is `http://127.0.0.1:1234/v1`. If you enabled authentication,
set `LM_STUDIO_API_KEY` in the environment before starting Athena.

For **Ollama**, install/download a model and run its local server. The default
endpoint is `http://127.0.0.1:11434/v1`. Select an installed local model rather
than a cloud-backed model if you want generation to remain on your computer.

Local connections require no OpenRouter account or key, and Athena never falls
back to a cloud provider. All service roles use the selected model, each in a
separate request. The model and its context window must fit your available
RAM/VRAM; a long book is generated chapter by chapter, but planning and review
prompts can still be large. Start with a short book and measure the result.
Local inference has no Athena API charge, but still consumes hardware resources
and electricity. Model downloads may require internet access.

Equivalent CLI commands (replace `YOUR_MODEL_ID` with the actual installed ID):

```powershell
python athena.py start --provider ollama --model "YOUR_MODEL_ID" --concept "Your story" --chapters 3 --background
python athena.py start --provider lmstudio --model "YOUR_MODEL_ID" --concept "Your story" --chapters 3 --background
```

Use `--base-url` for a different loopback port, keeping `/v1` at the end.
Local requests default to a 900-second timeout for slower hardware. Existing
jobs keep their snapshotted provider and model when resumed. The web UI binds
only to your computer; it is not an internet-facing multi-user application.
Closing the browser does not stop a book. Keep the UI terminal open to access
the interface, and keep your model server running while books are generated.

Provider documentation: [LM Studio](https://lmstudio.ai/docs/developer/openai-compat),
[Ollama](https://docs.ollama.com/api/openai-compatibility).

### Cloud / existing configuration

In **Settings**, select **OpenRouter**, paste your key into **OpenRouter API key**,
and select **Save key**. **Test key** checks authentication without generating
text. You can also test a pasted key before saving it. Then select **Find models**,
choose a model, and **Save settings**. Saving settings also saves a newly pasted key.

Keys are stored in Windows Credential Manager (no additional package on Windows),
or a supported OS keyring on macOS/Linux. The browser receives only configured/not
configured status; keys are not stored in settings JSON or copied into book folders.
Each Athena checkout has its own credential entry, accessible to workers running
as the same desktop user. A saved key takes precedence over environment/Hermes
keys. **Remove saved key** removes Athena's saved copy; an environment/Hermes key
can still be used afterward. The UI reports that fallback explicitly.

Secure vault access requires a normal desktop login session. On macOS/Linux,
install the requirements and enable the system keyring. If vault access is
unavailable, existing environment-based configuration remains supported.
Authentication reference: [OpenRouter key endpoint](https://openrouter.ai/docs/api_reference/limits).

Install dependencies with `python -m pip install -r requirements.txt`.
Set `OPENROUTER_API_KEY` in your environment (the existing Hermes `.env` fallback
is also supported). Review model IDs in `config/models.yaml` for your provider.
Model availability is not verified by offline tests.

```powershell
python athena.py start --concept "A lighthouse keeper receives letters from tomorrow" --chapters 3 --background
python athena.py status --job JOB_ID
python athena.py resume --job JOB_ID --background
```

Replace JOB_ID with the 32-character ID printed by start. Omit `--background`
to watch the worker in your terminal. Omit `--chapters` to let the planner choose
the chapter count. The worker infers unspecified creative details from the brief.

Each job snapshots services, config, and schemas into `jobs/JOB_ID/`. Existing
material in the root `08_Memory` is preserved and is not imported into new jobs.
Later changes to root config do not change existing jobs: edit that job's config
when deliberately changing a resumed run.

## Outputs and recovery

- `job.json`: status, active step, completed steps, timestamps, and last error.
- `worker.log`: background worker output.
- `08_Memory/manuscript.md`: assembled copy-edited chapters, in order.
- `08_Memory/metadata.json`: title, blurb, keywords.
- `08_Memory/delivery.json`: chapter and word counts.
- `08_Memory/usage.json`: attempted requests and reported token usage.

The worker checkpoints each planning stage, each completed chapter, each critique,
metadata, and manuscript assembly. Resume skips completed steps. An interrupted
intake reuses its saved conditions as context. Intake operates in draft mode:
it infers missing creative details, accepts short formats, and assigns outline
work to planning instead of blocking on marketing or publication decisions.
Conditional decisions get up to three attempts to resolve their requirements;
unresolved conditions still stop the job rather than becoming automatic approval.
An interrupted
step runs again, so an unfinished chapter can incur repeated calls. Hard process
termination may leave status as `running`; resume reclaims the released OS lock.
A second simultaneous worker is rejected. The computer must stay awake; this is
a detached local process, not a hosted scheduler or automatic reboot service.

Transient API failures retry with backoff. Invalid stage outputs get at most three
attempts. Chapter quality failures have a separate configured revision limit;
exhaustion stops the job without producing a completed manuscript. Inspect the
reports before resuming a quality failure; resuming starts that chapter's review
cycle again. Revisions are preserved within a cycle, and QA rejection blocks
delivery even when other reviewers give high scores.

`max_calls_per_job` (default 200) persists across resumes. Failed requests count.
`max_output_tokens` (default 8192) caps each response. These are request/output
limits, not a guaranteed dollar budget: input tokens, pricing, and failed requests
can affect bills. Usage totals include only responses received by this process.
Truncated output fails validation instead of being delivered as a finished chapter.

## Hermes integration

For the autonomous prototype, Hermes launches `athena.py start ... --background`
once and reports the job ID. It can read status and logs, or resume a stopped job.
It should not duplicate the pipeline with its own per-service subagents. The
worker uses separate model requests seeded with full service documents.

The older subagent/manual protocols are historical design references. This file
supersedes their runtime prohibition and human manuscript sign-off requirement
for autonomous draft generation. Publishing to external stores remains outside
this worker's scope. Legacy CLI commands (`chapter`, `publish`, `opening`, etc.)
have been replaced by the job-based `start`, `status`, and `resume` interface.

## Verification and next experiment

```powershell
python -m unittest discover -s tests -v
```

Tests use fake model responses, including injected failures during planning and
delivery. They verify control flow and artifact handling, not literary quality.
Provider tests also send real SDK requests to a simulated local HTTP server;
UI tests exercise book creation, status, resume, and download over HTTP.
With the UI running, `node tests/ui_smoke.mjs` checks the desktop/mobile browser
layout using an installed Chrome and Node.js (optional developer tools only).
Next, run a short real book and record cost, duration, editing effort, continuity
problems, and feedback from prospective readers. Long chapters still use one
generation call; scene-level generation, independent manuscript-wide evaluation,
DOCX/EPUB export, and a hosted customer interface remain future work.

# Archive Note

These seven files are earlier drafts of the same role slots, written back when the
project used `EMP-xxx` naming instead of `SRV-xxx`. They predate the Interface
Contract convention (`service_loader.py` requires a `## Interface Contract`
section with a fenced ```json block to produce a usable output schema), and in
one case (`SRV-002`) they even disagree with the canonical file on the role's
own name ("Literary Architect" here vs. "Story Architect" in `06_Services/SRV-002.md`).

`service_loader.load_service()` only ever reads `06_Services/SRV-XXX.md` —
these were never actually loaded by the runtime. They're kept here for
reference/history, not as usable service definitions.

**Canonical files live in `06_Services/` directly, one per numbered slot.**
If you want to merge good material from one of these into the canonical file
(e.g. a nice paragraph of flavor text), do it deliberately and then leave this
archive alone — don't un-archive them.

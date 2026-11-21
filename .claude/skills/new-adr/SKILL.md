---
name: new-adr
description: Record an architecture decision for devtools-rag-ingestion. Use whenever an approved decision is expensive to reverse — a technology, an architectural approach, a service boundary, an event contract — or when an existing ADR has stopped matching the code. Decides whether a record is needed, whether to correct one in place, and delegates the draft to the adr-writer subagent.
---

# Recording a decision

## 1. Does it need an ADR at all?

Write one when the decision is expensive to reverse (`docs/COLLABORATION.md`
section 8): choosing a technology, choosing between two architectural
approaches, defining a boundary between services, defining an event contract.

A decision that one commit can undo does not need one. Say so, and record the
reasoning in the pull request's "Decisions made" section instead.

**System-wide decisions belong in `devtools-rag-contracts/docs/adr/`**, not
here. That covers anything the retrieval service would also have to obey, such
as the event schema. If the decision is one of those, stop and say so.

## 2. New record, or a correction?

Records are corrected in place (ADR 0001). If the decision changes or
contradicts an existing record, that record is edited and its `Last revised`
date updated. `grep -ril "<topic>" docs/adr/` before assuming nothing exists.

## 3. Has Carlos approved the decision itself?

The ADR records a decision. It does not make one. If the approval, the rejected
alternatives and the reason for rejecting them are not in the conversation,
propose first (`docs/COLLABORATION.md` section 3) and stop.

## 4. Delegate the draft

Hand it to the `adr-writer` subagent with:
- the decision, in one sentence;
- every option considered, and why each rejected one was rejected;
- the costs Carlos accepted;
- where the facts came from, and which of them are guesses;
- the existing ADR to correct, if any.

## 5. Check what comes back

Before showing it to Carlos, confirm that it has at least one rejected option
with its reason, at least one real downside, the next sequential number, and
that it is in English. Then reference it from the code or `CLAUDE.md` wherever
the decision is enforced.

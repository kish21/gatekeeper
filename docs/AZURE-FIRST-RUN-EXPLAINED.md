# The first real Azure run, explained in plain English

> **What this is:** a non-technical account of 2026-08-24, the day GateKeeper was deployed to a real
> cloud for the first time. No jargon. If you want the engineering detail, read
> [the deploy guide](deploy/azure-container-apps.md) and [the test runbook](runbooks/verify-hosted-deploy.md).
>
> **The one-line version:** the guard did its job perfectly. The filing cabinet turned out to have no
> bottom.

## The cast, in everyday terms

GateKeeper is a **security guard for AI tools**. When an AI assistant wants to read a file, look
something up, or change a record, it doesn't get to do that directly — it has to go through the
guard. The guard checks who's asking, whether they're allowed, and writes down what happened.

Until today the guard only worked inside our own building. The question was: does it still work when
we put it out in the world?

Here's the vocabulary we used all day:

| Term | What it really is |
|---|---|
| **The recipe** | A file in the project describing how to assemble the app |
| **The lunchbox** | A sealed package holding the app plus everything it needs to run |
| **The kitchen and the shelf** | Where the cloud builds the lunchbox, and where it's stored |
| **The canteen** | The rented machine that opens the lunchbox and keeps it running |
| **The fridge** | A separate disk that survives restarts — where the logbook lives |
| **The doorman** | A check that rejects visitors arriving under an unrecognised address |
| **The logbook** | The tamper-proof record of every decision the guard made |

Nobody had to install anything. We handed the cloud the recipe; the cloud baked the lunchbox and ran
it. About fifteen minutes later there was a working web address anyone in the world could reach.

## What went right

Once it was up, we tested it from outside — a laptop in Belgium calling a machine in Amsterdam, over
the real internet.

**A normal user read a file.** Allowed, no friction. Governance that blocks everything is easy;
governance that lets legitimate work through is the hard part.

**A read-only user tried to write a file.** Refused. The refusal is the whole product:

> *"denied by cedar policy: role 'readonly' may not write demo-files::write_file (default-deny)"*

Two things matter there. It explained *why*, in terms a person can act on. And the file server never
heard the request — it wasn't blocked afterwards, it was stopped before.

**Someone turned up with a made-up pass.** Refused. Not "given limited access" — refused. An
unrecognised identity gets nothing at all.

That's the security claim, demonstrated on a real deployment rather than asserted in a document.

## The five stumbles on the way there

The deployment instructions had been written carefully, reviewed, and **never actually run**. Five
things broke. Every one of them was invisible to review and obvious within seconds of running.

**1. The kitchen's progress report crashed the phone line.**
The cloud narrated the baking process back to the laptop. Some of that text contained characters
Windows couldn't display, and the tool crashed mid-sentence. The baking carried on fine in the cloud —
we'd just lost the ability to watch. *Fix: stop narrating, check the result instead.*

**2. "Which building is that in?"**
One instruction asked the cloud to create storage but never said which folder it belonged to. Two
neighbouring lines got it right; this one was missed. *Fix: say which folder.*

**3. Saving over a file without renaming it.**
We rebuilt the app with a correction and gave it the same name as before. The cloud compared names,
saw no difference, and kept running the old copy. Our correction sat on the shelf, unused, while we
tested the old version and wondered why nothing changed. *Fix: every build now gets its own name,
stamped with the time.*

**4. A guest list nobody could match.**
The doorman had our address written down as *"that address, any room number."* But visitors arrive
saying only *"that address"* — no room number, because normal secure web traffic doesn't mention one.
So the doorman never found a match and turned everyone away. **Our own documentation recommended
this broken format**, which means this deployment had never worked as written. *Fix: list the address
both ways.*

**5. Two people writing in the same book.**
This one matters beyond today.

The logbook can only be written by one person at a time — that's a deliberate design rule, because
two people writing simultaneously would corrupt the page numbering that makes it tamper-proof.

But the cloud updates apps by **starting the new copy before shutting down the old one**. For a few
seconds, two copies existed, both reaching for the same logbook. The new copy found it locked, gave
up, and died. The cloud noticed the failure, kept the old copy running — and reported the deployment
as successful.

So every deployment that day silently did nothing, while telling us it had worked.

The design document said the logbook has exactly one writer "by construction." That's true while
running, and false during every single deployment. The database caught it and refused, which is the
good outcome. A more permissive system would have let both write and quietly corrupted the record.

*Fix: shut the old copy down completely first, then start the new one. Brief downtime, correct
records.*

## The big one: a fridge with no bottom

With all five fixed, everything passed. Then we asked the last question: **show us the logbook.**

The answer came back: *there is no logbook.*

The gateway had been writing entries. Every governed call succeeded, and the system refuses to let a
call through unless its record has been written — so the records must have been written. But:

- the logbook file on the disk was **completely empty** — zero bytes,
- a second person looking at the same disk saw **no logbook at all**,
- and after a restart, everything was **gone**.

The cause is a mismatch nobody would spot by reading code. The logbook software assumes it's writing
to a disk it fully controls. We'd given it a **network file share** — storage that lives elsewhere and
is reached over the network. Network shares don't honour the guarantees that software depends on, so
writes that *appear* to succeed aren't really committed, and a second reader sees an empty file.

We had put the filing cabinet in a room with no floor. Documents went in. Nothing stayed.

**This is the most valuable thing we found**, and it's worth being blunt about why: a guard who checks
every badge correctly but keeps no record has failed at the job. The whole promise of this product is
*provable* governance. Half of that promise didn't survive contact with a real cloud.

## Where things stand

| Claim | Result |
|---|---|
| Runs on the internet, visible and monitorable | ✅ proven |
| Checks identity and refuses what it should | ✅ proven |
| Keeps a record you can inspect | ❌ failed |
| Record survives a restart | ❌ failed — everything lost |

Half proven, half disproven — and the disproven half is now a documented, tracked problem rather than
a pleasant assumption.

## What happens next

The fix is a **choice**, not a repair, which is why it wasn't done in the same breath:

1. **A different kind of shared storage** (one that does honour the guarantees). Smallest change,
   slightly more expensive.
2. **A dedicated disk** rather than a shared one. Straightforward, less flexible.
3. **A proper database** for hosted deployments instead of a file. Biggest change — and the one that
   would also remove the "only one copy may run" restriction.

Tracked as [issue #54](https://github.com/kish21/gatekeeper/issues/54). The fixes and this account
are in [PR #53](https://github.com/kish21/gatekeeper/pull/53).

## The lesson worth keeping

The deployment instructions were written by someone competent, reviewed, and documented with real
care. They were also **wrong in five places and built on unsound storage** — and not one of those
faults was visible until someone ran them.

"It should work" and "it worked" are different claims. Today converted one into the other, and the
gap between them was six defects deep.

The project's own notes had been honest about this all along, calling the Azure proof "docs-only"
rather than done. That honesty is exactly why today produced findings instead of surprises.

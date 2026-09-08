# A day at Northwind Bank — the GateKeeper story

*A use case told as a story, for people who do not write code. If you have ever wondered
"what does GateKeeper actually do, and why would anyone want it?", this page is for you. Nothing
here requires you to read a settings file or run a command.*

---

## The people in this story

| Who | Role in the story |
|---|---|
| **Priya** | Head of operations at Northwind Bank. Wants the team to use AI, but is nervous. |
| **Marcus** | Support engineer. Handles customer tickets all day. |
| **Dana** | Finance analyst. Only needs to *look things up*, never change anything. |
| **The assistant** | An AI helper the bank has rolled out. It can read files, open tickets, and update records on the bank's behalf. |
| **The auditor** | Visits once a quarter and asks one question: "Prove it." |

GateKeeper itself never speaks in this story. It is the guard at the door, and good guards are
quiet.

---

## Chapter 1 — The problem Priya could not sleep on

Northwind rolled out an AI assistant to the support team. It was a hit. Marcus could say "find
every ticket from this customer and summarise them", and it would. Then he could say "open a
follow-up ticket", and it did that too.

Priya liked the speed. What she did not like was the answer she got when she asked three simple
questions:

1. **Who is the AI acting as?** When it changes a record, whose name is on it?
2. **What is it allowed to do?** Could someone talk it into deleting something?
3. **What did it actually do last Tuesday?** Not what it *said* it did. What it *did*.

Nobody could answer. The assistant talked straight to the bank's tools, with a shared password,
and left behind an ordinary log file that anyone with access could quietly edit.

That is the gap GateKeeper fills. Everything below is what changed after Northwind put it in.

---

## Chapter 2 — The guard moves in

Northwind's IT team installed GateKeeper on the machine where the assistant runs. From that day,
the assistant no longer talks to the bank's tools directly. Every request goes **through the
guard** first.

The team made three decisions, all written in plain settings files, no programming:

- **Which tools the guard protects.** The ticket system, the document store, and a customer
  lookup service. Any tool the bank adds later goes on the same list.
- **Who gets which badge.** Marcus gets an **operator** badge: he may read and make changes. Dana
  gets a **read-only** badge: she may look, never touch. Priya keeps an **admin** badge for
  emergencies.
- **The rulebook.** A short, readable list of rules: read-only badges may only read. Operators
  may read and write. Everything else is refused by default.

The assistant itself was not changed. The tools were not changed. The guard simply moved into the
hallway between them.

---

## Chapter 3 — Marcus has a normal day

Marcus asks the assistant: *"Pull up ticket 4471 and summarise it."*

Behind the scenes, in a fraction of a second, the guard does four things:

1. **Checks the badge.** The request arrives with Marcus's badge. The guard confirms it is real
   and sees that Marcus is an operator.
2. **Checks the rulebook.** Reading a ticket is a read. Operators may read. **Allowed.**
3. **Writes it in the logbook.** *Before* anything happens, the guard records: who, what, when,
   and the decision. This entry is chained to the one before it, like a bead on a string.
4. **Opens the door.** The request goes to the ticket system, the answer comes back untouched,
   and the outcome is recorded too.

Marcus sees the summary. He never notices the guard. That is the point.

Later he says: *"Open a follow-up ticket for the customer."* That is a write. Same four steps,
same result: allowed, recorded, done. The ticket is created and the logbook shows exactly which
badge asked for it.

---

## Chapter 4 — Dana tries something she should not

Dana, in finance, asks the assistant: *"Update the customer's address to the new one in this
email."*

Dana is not being malicious. She simply does not know that address changes are the support team's
job. But the email she pasted could just as easily have been a scam telling the AI to change bank
details.

The guard does not care about intent. It does the same four things:

1. **Badge:** Dana, read-only.
2. **Rulebook:** updating a record is a write. Read-only badges may not write. **Denied.**
3. **Logbook:** the denial is recorded, with the reason, just like an allow would be.
4. **Door stays shut.** The tool is never contacted. Nothing changes anywhere.

Dana gets a clear message: *denied by policy, role "readonly" may not write.* She asks Marcus to
do it instead, which is exactly the process the bank wanted all along.

This is the moment Priya's second question got its answer. It does not matter how persuasive the
instruction is, or whether it came from a person or a poisoned email. A read-only badge cannot
write, and that rule lives in the guard, not in the AI's judgement.

---

## Chapter 5 — A stranger at the door

One evening, a request arrives with a badge nobody has issued. Maybe an old script, maybe
something worse.

The guard checks the badge, finds no match, and refuses before reaching the rulebook at all.
*Unknown or missing token.* The attempt is recorded. No tool ever hears about it.

Priya's first question, "who is the AI acting as?", now has a firm answer: **only someone holding a
badge the bank issued, and the logbook says which one.**

---

## Chapter 6 — The auditor arrives

Three months later, the auditor sits down with Priya and asks: *"Show me everything the AI did in
March, and prove that nobody edited the record afterwards."*

Priya runs two commands. That is the entire audit.

**"Show me everything."** The logbook lists every action: Marcus's reads and writes, Dana's
denied attempt, the stranger's refused badge. Each entry shows the badge, the tool, the decision,
the reason, and the time.

**"Prove nobody touched it."** Here is the part that makes GateKeeper different from a normal
log. Every entry in the logbook is sealed with a secret key and chained to the entry before it.
If anyone alters an entry, deletes one, or slips a fake one in, the chain breaks at that exact
spot. The integrity check walks the whole chain and reports **clean**.

The auditor wants to see it fail, so Priya opens a copy of the logbook and changes one word in
one entry. She runs the check again. It stops and points at the exact record that was tampered
with.

The auditor writes one line in the report: *Evidence verified independently. No reliance on the
vendor's word.*

That was Priya's third question. She does not need to trust the AI, or even trust GateKeeper. She
can **check**.

---

## Chapter 7 — Northwind grows

A few things happen over the next year, and none of them require a developer:

- **A new tool.** The bank adds a GitHub server so the assistant can raise engineering issues.
  IT adds five lines to the settings file: the tool's name, which of its actions are reads, and
  which are writes. The existing rulebook applies to it instantly. Dana still cannot create an
  issue. Marcus can.
- **A password stays secret.** The GitHub tool needs an access token. It goes in a private file
  the guard reads at start-up. It never appears in the settings, the logbook, or any screen.
- **The whole company shares one guard.** Instead of one copy per laptop, IT runs GateKeeper as
  a small service in the cloud. Every assistant in the company points at it over the network.
- **Real company logins.** Static badges are swapped for the bank's own single sign-on. Marcus's
  badge is now simply Marcus's corporate login. When he leaves, his access ends the same day his
  account does.
- **A dashboard.** IT can see how many requests the guard handled, how many it denied, and gets
  an alert if the logbook chain is ever broken.

---

## What the story does not claim yet

Be honest with anyone you tell this story to. Today, when Marcus asks for a write, it goes
straight through and is fully recorded. **The next milestone** adds two more steps for risky
writes: the guard asks an AI to score how dangerous the action is, and a human signs off before
it happens. Until that ships, do not say "every write needs approval". Say "every write is checked
against the rulebook and recorded in a logbook nobody can quietly edit", because that is true
today.

---

## The story in one table

| Priya's question | What the guard does | Where it shows up |
|---|---|---|
| Who is the AI acting as? | Checks a badge on every request; refuses unknown badges | The logbook names the badge on every line |
| What is it allowed to do? | Applies a readable rulebook; denies by default | Dana's denied write, with the reason |
| What did it actually do? | Records every decision before acting, sealed and chained | The auditor's clean integrity check, and the tamper it caught |

---

## Want to see it happen?

The repository ships a five-minute narrated demo that plays almost exactly this story on your own
machine: an operator's read allowed, a read-only write denied, a real third-party tool governed
with no code, the logbook verified clean, and a deliberate tamper caught.

```bash
make demo
```

For the full plain-English explanation of the parts, read [How it works](HOW-IT-WORKS.md). For the
hosted, whole-company version, read [GateKeeper on Azure](SHOWCASE-AZURE.md).

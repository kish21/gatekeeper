# What you can put behind the guard

*For Priya — and anyone else who has to decide whether this is worth doing. No code, no settings
files. If you have seen a demo of this, you have probably only seen it guarding **files**, and
files are the least interesting thing it does.*

---

## First, the product in four sentences

Your team's AI assistant can reach real company systems. That is the point of it, and it is also
the problem: it acts under one shared login, nothing stops it doing something drastic, and the
only record is a log file anyone could edit.

GateKeeper is a guard that sits between the assistant and those systems. Every single action goes
through it: it checks **who** is asking, checks that against **your rules**, writes it in a
**record that cannot be quietly altered**, and only then lets it through — and anything that
*changes* something stops and waits for a named person to say yes.

Nothing else changes. Your assistant is not modified. Your systems are not modified. The guard
just moves into the doorway.

*(If you want the longer version with a picture: [HOW-IT-WORKS.md](HOW-IT-WORKS.md).)*

---

## Why every demo shows you files

Because a file is easy to show in a room. "The assistant tried to write `notes.txt` and had to
wait for a person" — everyone gets it in one second.

But nobody's real worry is `notes.txt`. Your worry is the assistant emailing a customer the wrong
thing, or changing a customer's record, or merging code nobody reviewed. Those are the ones this
was built for, and they work exactly the same way.

---

## The five systems that are ready today

These ship with the product, working, out of the box:

| System | What the assistant can look at | What it can change |
|---|---|---|
| **Your mailbox** (Outlook or Gmail) | Search and read mail | Send mail |
| **Your customer database** | List tables, run look-ups | Run statements that change data |
| **Jira** | Search and read tickets | Create tickets, move them, comment |
| **SharePoint** | Search and open documents | Edit, delete, **share** documents |
| **GitHub** | Read issues and files | Open issues, open and **merge** pull requests, delete branches |

Reading is instant — nobody wants to approve "look up this customer" forty times a day. Everything
in the right-hand column stops and waits for a person.

Now the part that matters more than the list. Some things do not wait for a person, because
waiting implies somebody might say yes. These are refused outright, for everybody, including your
own administrators:

- **Anything writing to your main code branch.** Changes ship through review, like everyone else's.
- **Destructive database statements** — `DROP`, `TRUNCATE`, a delete with no limit — wherever in
  the request they are hidden.
- **Edits to the customer table.** An assistant does not amend customer records. Full stop.
- **Mail to an address outside your company.** This is the one that leaks data, and it is the one
  people forget to watch.
- **Writes to anything under a secrets path.** Readable, never writable.

Those five are examples with sensible instincts, and they are a plain-language file you change.
Yours will be different — the point is that this is where a rule like "never email outside the
company" stops being a policy on paper and becomes something a machine enforces every time.

---

## And anything else you already own

The five above are not a fixed menu. There is a common standard for connecting AI assistants to
systems, and **anything that speaks it can go behind the guard** — with no programming, no change
to the system itself, and no change to the assistant.

In practice that means the tools already on your desk: Slack, Confluence, ServiceNow, Salesforce,
your data warehouse, a scheduling system, an internal API your own team wrote.

The honest caveat: the system needs a connector for that standard to exist. Most large vendors now
publish one, and a connector for an internal system is a small piece of work for one developer. If
your assistant can already use a system today, it can be governed today.

---

## What it costs to add one

Roughly ten minutes for someone technical, per system:

1. **Name it**, and say how it is reached.
2. **Give it the credential** it already needs — that lives in a private file, never in the rules,
   and never reaches the assistant. The assistant gets a badge that says who *it* is; only the
   guard holds the keys to the actual systems.
3. **Say which of its actions change something.** This is the only real judgement call, and it is
   the one to be conservative about: anything you are unsure of, list it as a change. The worst
   case is somebody approves a few things they did not need to.

No code is written. Nothing is rebuilt. The guard does not know or care which system it is — that
is deliberate, because it means the twentieth system costs the same as the second.

---

## One thing to know before a demo

The five systems above ship as **stand-ins**: local copies with the same actions and the same
names as the real SharePoint, Jira, GitHub, database and mailbox, holding a little invented data.
That is so anyone can see the whole thing work in twelve minutes without a tenant, an admin, or a
credential.

They are not pretending to be real, and you should say so in the room. Swapping one for your
actual system is the ten minutes described above — the credential is the slow part, and it is slow
because of *your* approvals process, not this.

---

## "But what stops someone just not using it?"

The honest answer first, because it is the second question every buyer asks and a vague answer
should worry you.

A guard governs what walks through the door it is standing in. If an assistant on someone's laptop
talks straight to GitHub using its own key, this never sees it. No product that sits in the middle
can fix that from the middle.

So the enforcement does not come from the guard alone. It comes from **making the other route stop
working** — and every part of that is done by your administrators, with nothing at all for your
staff to do.

### The four levers, in the order they matter

1. **Take the keys off the laptops.** This is the one that does the real work. Right now the
   assistant on someone's machine holds a key to GitHub, a connection to the database, a grant on
   the mailbox. Move those into the guard and cancel the copies. Going around it is now not
   *blocked* — it is **dead**, because there is nothing left to go around it with. Your people
   carry a badge that says who they are; only the guard holds keys to the actual systems.

2. **Push the setting from your device management.** The same system that already puts the VPN and
   the printer on a company laptop puts one line in the assistant's settings, pointing it at your
   gateway. The employee opens their assistant and the tools are simply there. They never typed an
   address, and there is nothing for them to get wrong.

3. **Use the login they already have.** They sign in with the company account they use every
   morning, and what they are allowed to do comes from the groups they are already in. No new
   account, no password to keep, nothing to set up.

4. **Close the road as a backstop.** Company laptops can reach your systems only through the
   gateway's address. This catches the rare case where somebody obtains a key anyway.

Lever 1 is the decision. Levers 2 and 3 are what make it invisible to staff. Lever 4 is the belt
alongside the braces.

### At a hundred people, this gets easier, not harder

A common worry is that every employee now needs their own credential to look after. They do not —
and if anyone proposes that, it is the wrong design:

| | Handing out individual keys | Using your company login |
|---|---|---|
| A new joiner | Somebody creates a key and sends it to them | They are added to a group. That is all |
| Someone leaves | You must find and cancel *their* key | Their account is disabled and access ends everywhere, including here, the same second |
| Someone changes team | Issue a new key | Change which group they are in |
| Secrets in circulation | One per person | **None** |

The last row is the point. With the company login there is no personal secret to hand out, rotate,
or chase. Every single request is checked against your identity provider as it happens, so somebody
switched off at nine o'clock is refused at nine o'clock. And there is no fallback role: an employee
who is in no group at all is refused, not quietly given the benefit of the doubt.

Which leads to the thing worth remembering out of this whole page:

> **You are not enforcing on a hundred employees. You are enforcing on about five keys.**

One per system, held by the guard and nowhere else. That is why this does not get more expensive as
the company grows, and why it does not depend on anybody remembering to do the right thing.

### What it does not do yet

It does not *notice* that somebody went around it. If a determined engineer keeps a personal key to
a system, the guard is silent — not because it permitted anything, but because it never saw it.

That is fixable and worth asking for: comparing our record against each system's own log would show
any action that happened without passing through here, with a name and a time on it. It is not built
today, and you should treat "nobody can bypass it" as meaning *nothing gets through the guard
unchecked* — not *nobody can walk around the building*.

---

## What you actually have to decide

Three things. None of them is technical, and nobody can decide them for you:

1. **Which systems go behind the guard**, and in what order. Start with the one that would hurt
   most if the assistant got it wrong at 4pm on a Friday.
2. **Who gets which badge.** Most people should be able to *look* at everything and *change*
   nothing. A smaller group may propose changes. A named few may approve them — and nobody
   approves their own.
3. **Which changes are never allowed at all**, whoever asks. That is the list in the middle of
   this page, and it should end up being yours rather than ours.

Everything else — the deployment, the record, the approvals page — is already built and waiting.

---

*Next: [USE-CASE-STORY.md](USE-CASE-STORY.md) tells this as a day at a bank. If you want to see it
running, [DEMO-COMPANY.md](DEMO-COMPANY.md) is a twelve-minute script with all five systems.*

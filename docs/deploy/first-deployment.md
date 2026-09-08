# Your first deployment, start to finish

This is the whole thing in one sitting: about half an hour, mostly waiting. No prior knowledge of
Azure, databases or containers is assumed. Every step says **why** it is there, because a step you
do not understand is a step you cannot fix when it goes wrong.

If you want the terse reference instead — every setting, every knob — that is
[azure-container-apps.md](azure-container-apps.md). This page is the story.

---

## The situation you are solving

Someone at your company has connected an AI assistant to real systems. It can open pull requests,
run database statements, send mail. That is genuinely useful, and it is also the first time
software has been able to *act* on your company without a person in the loop.

You now have three questions you cannot answer:

1. **Who did that?** The assistant acts under one shared account, so the log says "the bot".
2. **Should it have?** Nothing stops the assistant deleting the main branch except its own judgement.
3. **Can you prove any of it later?** When an auditor asks what happened in March, you have chat
   logs.

GateKeeper sits between the assistant and those systems and answers all three. Nothing reaches a
real system without passing through it. Every call is checked against written rules, risky writes
stop and wait for a named human, and every one of those events is written into a tamper-evident
record before anything happens.

That is what you are about to put on the internet.

---

## Before you start

Two things, five minutes.

**1. The Azure command line, signed in.**

```bash
az login
```

If `az` is not found, install it from <https://aka.ms/installazurecli>. On Windows, do all of this
from **Git Bash**, not PowerShell — the script is a bash script.

*Why:* everything below is created by the script talking to Azure as you. It never asks for a
password; it borrows the session `az login` just made.

**2. This repository, on your machine, and you are in its folder.**

```bash
cd gatekeeper
```

*Why:* the script builds the gateway's image from the code in this folder. It has to be able to see
it.

**Optional, but do it now if you can: a Slack or Teams webhook.**

```bash
export GK_APPROVAL_WEBHOOK='https://hooks.slack.com/services/...'
```

*Why:* when the assistant tries a risky write, GateKeeper stops it and waits for a person to say
yes. If nobody is told it is waiting, nobody says yes, and after five minutes it gives up and
refuses the call. That is safe, but it feels broken. The webhook is how a person finds out. You can
add it later; a channel you already have works fine.

---

## Step 1 — One command

```bash
bash scripts/deploy_azure.sh
```

Then leave it alone for about fifteen minutes. It prints what it is doing as it goes.

Here is what it is building, and why each piece exists:

| It creates | In plain terms | Why you need it |
|---|---|---|
| A **resource group** | A labelled box holding everything else | So you can delete the whole thing later with one command and know nothing was left behind |
| A **container registry** | A private shelf for your built software | Azure builds the image there, so you do not need Docker on your laptop |
| A **Container Apps environment** | The estate the app runs in | Gives you an HTTPS address with a real certificate, without you configuring a web server |
| A **PostgreSQL database** | An ordinary managed database | **This is the audit trail.** See below — it is the most important line in the table |
| One **container app** | The gateway itself, always on | The thing that actually stands between the assistant and your systems |
| Four **secrets** | Passwords, kept by Azure, not by you | The tokens are generated fresh for your deployment; the repository's demo tokens never touch the internet |

**Why the audit trail is in a database and not a file.** The first time this was deployed for real,
the record was a file on shared storage — and it silently failed. The file stayed at zero bytes
while calls were being served, a second program could not read it at all, and a restart lost every
record. An audit trail that quietly loses records is worse than none, because you trust it. Moving
it into a managed database fixed all three: the records outlive the container, anyone can read them,
and several copies of the gateway can write at once without tangling the record. That is why a
database is created by default, and why it costs a few euros a month.

When it finishes it prints **DEPLOYED** and your address, something like
`https://gatekeeper.bluesky-1234.westeurope.azurecontainerapps.io`. It also prints the exact
commands for every step below, filled in with your names — you can copy them from your terminal
rather than editing the ones here.

*If it stops with an error*, it tells you which of the six things it was doing. The most common
cause is a subscription that has never used a service before; the script registers what it can and
names what it cannot. Re-running is always safe: the names are fixed, so a second run continues
where the first stopped rather than making a duplicate of everything.

---

## Step 2 — Prove it governs

You now have a live thing. Do not trust it yet. Ask it to prove itself, from your own machine,
across the public internet — the same path anyone else would take.

Fetch the two credentials it generated for you:

```bash
IDS=$(az containerapp secret show -n gatekeeper -g gatekeeper-rg --secret-name identities --query value -o tsv)
UIT=$(az containerapp secret show -n gatekeeper -g gatekeeper-rg --secret-name ui-token --query value -o tsv)
```

Then run the probe:

```bash
python -m scripts.probe_hosted --url "https://<your address>" \
  --operator-token "$(echo "$IDS" | cut -d';' -f1 | cut -d: -f3)" \
  --readonly-token "$(echo "$IDS" | cut -d';' -f2 | cut -d: -f3)" \
  --ui-token "$UIT"
```

Eight checks, one line each:

| Check | The question it answers |
|---|---|
| T1 LIVE | Is it reachable over HTTPS at all? |
| T2 GOVERNED LIST | Does it show the systems it is guarding? |
| T3 ALLOW | Can a normal user do a normal thing? A gate that blocks everything is not a gate |
| T4 DENY (RBAC) | Is a read-only user refused a write? |
| T5 DENY (IDENTITY) | Is a stranger with an invented token refused? |
| T6 OBSERVABLE | Can your monitoring see it? |
| T7 DURABLE AUDIT | Can the record be read back **from a different program**? |
| T8 SURVIVES RESTART | Are the records still there after the gateway is replaced? |

**Why these eight and not "it returned 200".** A gateway can fail in a way that looks like success:
a broken connection also produces "the call did not go through", which is indistinguishable from
"the call was refused" if you are not careful. The probe keeps *allowed*, *denied* and *error*
separate, so a network fault can never be scored as a passing security check.

T7 and T8 are the two that matter most, and the two that failed on the first real deployment. T7 is
run for you. T8 you have to trigger, because it means genuinely destroying the running gateway:

```bash
az containerapp revision restart -n gatekeeper -g gatekeeper-rg \
  --revision "$(az containerapp show -n gatekeeper -g gatekeeper-rg --query properties.latestRevisionName -o tsv)"
```

Wait a few seconds, then run the **same probe again**, adding the number of records it reported
last time:

```bash
python -m scripts.probe_hosted --url "https://<your address>" ... --ui-token "$UIT" --expect-at-least 4
```

*Why the number:* "the record exists" is easy to pass — a brand new empty record exists too. Naming
how many entries must still be there is the difference between checking it works and checking it
did not quietly start over.

---

## Step 3 — Watch a person stop a machine

This is the part to show someone else. Open the desk in a browser:

```
https://<your address>/ui
```

It asks for a credential once. There are two kinds, and the difference *is* the demonstration.

**Paste the desk token first** (`echo "$UIT"`). Now have the assistant attempt something a company
would care about — a write. It does not happen. It appears on the desk and *waits*, and the
assistant sits there, blocked.

Press **Approve**. You are refused.

That is correct. The desk token proves you are allowed to *look* at the desk. It says nothing about
who you are, and "someone who could open the page" is not a person an audit record can name.

**Now sign in with the approver's own token:**

```bash
echo "$IDS" | cut -d';' -f3 | cut -d: -f3
```

Press **Approve** again. It goes through, and the record says who did it and how they proved it.
Press nothing for five minutes instead and the write is refused on its own.

Two more refusals worth trying, because they are the ones people assume are not really enforced.
Sign in with the read-only user's token: you can watch, you cannot decide — reaching the desk is
not the same as being an approver. Sign in as the person who *made* the call and approve their own
request: refused, always.

**Why so strict.** "Approved by Priya" is worth nothing if anyone could have typed the word Priya
into a box. On a public address a typed name is refused outright; the approval must be backed by a
credential, the approver must actually hold the approver role, and nobody may approve their own
request. What lands in the record is not a name someone claimed, but a name that was proven — and
*how* it was proven.

## Step 4 — Read the record

```bash
az containerapp exec -n gatekeeper -g gatekeeper-rg --command "gatekeeper tail --with-id"
az containerapp exec -n gatekeeper -g gatekeeper-rg --command "gatekeeper verify"
```

`tail` shows what happened. `verify` answers a different and harder question: **has anyone edited
it since?**

Every entry carries a fingerprint of itself *and of the entry before it*, so they form a chain.
Change one old line and every fingerprint after it stops matching. `verify` walks the chain and
says either "intact" or exactly where it breaks. Nobody can quietly delete the inconvenient
Tuesday.

**Why the record is written before the action, not after.** If it were written afterwards, then a
call that crashed halfway, or a gateway that was killed mid-flight, would leave no trace of an
action that may well have happened. GateKeeper writes what it is about to do first, then does it,
then records how it went. The record can say "we tried and do not know the outcome". It can never
say nothing at all.

---

## What it costs, and how to make it go away

Roughly **€20-30 a month**: one small always-on container, a basic registry, and the smallest
managed database Azure sells.

All of it, gone:

```bash
az group delete -n gatekeeper-rg --yes --no-wait
```

That is what the resource group was for. Nothing survives it, including the audit record — so
export anything you want to keep first (`gatekeeper export --format cef`).

---

## When you are ready to use it for real

Everything above is a working deployment. Three things turn it from a working deployment into your
company's deployment, none of which needs a rebuild:

1. **Your own login.** Right now people are identified by tokens the script generated. Point it at
   your corporate identity provider and they are identified by *who they are*, with roles coming
   from the groups they are already in. Set four environment variables on the app;
   [the OIDC guide](../features/oidc-identity.md) has them.
2. **Your own rules.** The rules that ship are examples with sensible instincts: not the default
   branch, not customer tables, not mail to outside addresses, not writes to secrets. Yours will be
   different. They are a plain text file — [the policy guide](../features/argument-aware-policy.md)
   explains how one is read.
3. **Your own definition of risky.** Out of the box every write waits for a person, which is
   correct and quickly annoying. Risk scoring lets ordinary writes through and stops the ones that
   deserve it. [Risk scoring](../features/risk-scoring.md) is one block of config.

Do them in that order. Login first, because until people are really identified, everything the
record says about *who* is a guess.

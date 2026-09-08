# Feature — Risk scoring (M2.1): spending attention where it matters

> Holding every write is the right way to start and the wrong place to stay.

## The problem with holding everything

A person who approves forty writes a day is not reviewing forty writes. They are clicking. The
fortieth request looks exactly like the first, the argument preview is 500 characters they have
stopped reading, and the one that mattered goes through with the rest. Approval fatigue does not
announce itself; it just quietly turns a control into a formality.

Human attention is the scarce resource this product spends. Risk scoring is how it stops spending
it on `createJiraIssue`.

## How a write is scored

Every write gets a score from the same attributes the policy sees (`domain/arguments`): a base
value, plus the weight of each signal that matches, capped at 1.0.

```yaml
risk:
  hold_at: 0.5             # >= this stops at the desk
  base: 0.3                # a write with no signals is still a change to a real system
  signals:
    - id: production-branch
      weight: 0.4
      attribute: branch
      equals: [main, master, production, prod, release]

    - id: recipient-outside-the-company
      weight: 0.4
      attribute: domains
      outside: [corp.example]      # anything not yours

    - id: large-amount
      weight: 0.3
      attribute: amount
      at_least: 10000

  always_hold: [github:merge_pull_request, database:execute]
  never_hold: []
```

Matchers: `equals` (attribute is one of these), `text` (a string appears anywhere in the call),
`at_least` (a number reaches this), `outside` (a value that is *not* in your list), `present` (the
attribute exists at all).

Against real-looking calls, with the shipped signals:

| Call | Score | Why |
|---|---|---|
| `jira:createJiraIssue` "Investigate the billing job" | 0.30 | no signals — ordinary work |
| `mail:send_email` to a colleague | 0.30 | no signals |
| `mail:send_email` to a personal address | 0.70 | recipient outside the company |
| `sharepoint:upload` to `/prod/secrets/` | 0.70 | secrets path |
| `finance:transfer` 25 000 | 0.60 | large amount |
| `database:update_row` on `customers` | 0.60 | customer data |
| `github:merge_pull_request` | 1.00 | always held |

At `hold_at: 0.5` the bottom two rows of ordinary work pass straight through — recorded, as
everything is — and the desk shows the five that deserve a person.

## Two rules this must never break

- **The score never decides whether a call is permitted.** The rulebook does that. A call the
  policy denies is denied whatever it scores; a call the policy allows is *held or not held*.
  Risk allocates attention, not authority.
- **An unscored write is held.** Absence of a score is never a reason to skip the human, so a
  scorer that fails or a tool nobody anticipated falls back to the cautious answer.

## It is arithmetic, not a model

Deliberately:

- **A score has to be explainable.** The ledger records `[risk 0.70: recipient-outside-the-company]`
  next to the decision. Someone woken up at 2am can read why, and an auditor can reproduce it a
  year later.
- **It sits in a fail-closed path.** A gateway that needed a network call to score a write would
  deny every write when that service was down.
- **The signals are your company's, not ours.** They are config for the same reason the policy is:
  what counts as risky differs per company and changes over time.

An LLM classifier fits the same seam — a scorer is anything with `score()` — and would earn its
place on the calls where wording matters more than attributes (is this SQL destructive in a way
`text:` misses?). It is not shipped, because a non-deterministic score in the audit trail is a
liability until the deterministic one is exhausted.

## Start at zero

The shipped default is `hold_at: 0` — **every write waits for a person**, which is what an
untuned gateway should do. Run it that way until the activity view shows you what your assistants
actually do, then raise the threshold with signals that match your business. The tests assert this
default, so it cannot drift quietly.

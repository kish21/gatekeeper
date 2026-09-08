# Feature — Rules that read the arguments

> Closes the gap a reviewer put first: the policy could see *who* and *which tool*, but not *what
> the call would actually do*.

## The problem

`delete_branch` on `main` and `delete_branch` on `feature/spike` were the same sentence to the
gateway. So were `SELECT 1` and `DROP TABLE customers`, and a mail to a colleague and a mail to a
personal address with the customer list attached.

Every control an enterprise actually has is about the object, not the verb:

- not the production branch
- not the customers table
- not to an address outside the company
- not over ten thousand
- not under `/secrets/`

None of those can be written as "role × tool".

## What a rule can see now

Cedar receives a bounded `context` describing the call:

| In a rule | What it is |
|---|---|
| `context.branch` | `branch`, `ref`, `head`, `base`, `branch_name` — whichever the server calls it |
| `context.path` | `path`, `file`, `filename`, `file_path`, `key` |
| `context.table` | `table`, `table_name`, `collection`, `dataset` |
| `context.statement` | `query`, `sql`, `command`, `script`, `jql` |
| `context.recipients`, `context.domains` | addresses, and the mail domains they resolve to |
| `context.amount` | `amount`, `total`, `value`, `price` (numbers only) |
| `context.repo`, `context.site`, `context.identifier` | the rest of the common vocabulary |
| `context.args."issue.fields.summary"` | every argument, flattened, if you want the raw one |
| `context.arg_keys` | which arguments were *supplied* — presence, not value |
| `context.arg_text` | every string in the call, lowercased, for `like` patterns |
| `context.principal`, `.role`, `.tenant`, `.upstream`, `.tool` | who and where |
| `resource.upstream`, `resource.tool` | so a rule can name a whole server |

The normalization is the part that matters in a company with more than one tool server: a rule
written once about "the branch" applies to GitHub, GitLab and an internal server that calls it
`ref`, instead of silently not applying to two of them.

## Writing one

```cedar
@id("no-writes-to-the-default-branch")
forbid (principal, action == Action::"write", resource)
when { context has branch && (context.branch == "main" || context.branch == "master") };
```

Two things make this safe to rely on:

- **`forbid` beats every `permit`,** including `admin`'s. A guardrail that an admin can walk
  through is a suggestion. There is a test that an admin is stopped.
- **The `@id` is the name in the audit trail.** A denied call records
  `forbidden by rule [no-writes-to-the-default-branch]`, so the person who was denied knows which
  rule to read — or to argue with. Give every rule an id.

`policies/gatekeeper.cedar` ships five guardrails of this shape (default branch, destructive SQL,
customer tables, outside mail domains, secret paths). They are examples with teeth: delete the
ones that do not match your company and write your own.

## Bounded on purpose

Arguments can be enormous, deeply nested, or hostile, and a policy-evaluation failure is a
fail-closed deny — an outage, not just a slow call. So the context is capped on every axis:
40 keys, 512 characters per string, 20 list items, two levels of nesting, 4000 characters of
searchable text. Anything that is not a string, number or boolean is dropped.

Nothing here is persisted. The ledger keeps the keyed payload hash, as it always has; this is what
the policy sees for the microsecond it takes to decide.

## What it does not do

- **It does not understand meaning.** `arg_text like "*drop table*"` is a string match. An
  assistant asked to be clever about spacing or comments can write SQL that misses it. Argument
  rules raise the floor; they are not a semantic firewall. That is what the human hold — and,
  above the threshold, the risk score — are for.
- **It cannot see what it was not given.** A server that hides the destructive part of a call
  behind an opaque id (`execute_saved_query: 42`) gives a rule nothing to match on. Annotate that
  tool as a write and let it stop at the desk.
- **It does not replace the classification.** Whether a call is a read or a write still comes from
  `upstreams.yaml` (or the name patterns). Arguments refine *which* writes are allowed.

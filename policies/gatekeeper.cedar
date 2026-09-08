// gatekeeper.cedar — policy-as-code. THIS FILE IS THE AUTHORIZATION CONTRACT (ADR-002).
//
// Cedar is deterministic and analyzable, and it denies anything no `permit` matches, so the
// gateway is fail-closed by construction. A `forbid` always beats a `permit`, which is what makes
// the guardrails at the bottom of this file absolute: no role, not even admin, gets past them.
//
// The request a rule decides on:
//   principal  User::"alice"        a member of Role::"operator" — the role carries the grants
//   action     Action::"read"       or "write", from the call's classification
//   resource   Tool::"github::create_issue"     .upstream = "github"  .tool = "create_issue"
//   context    what the call would actually DO:
//                context.branch / .path / .repo / .table / .statement / .recipients / .domains
//                    / .amount / .site / .identifier   — the same concept under one name, whatever
//                                                        the server happens to call its argument
//                context.args."<name>"   the raw arguments, flattened ("issue.fields.summary")
//                context.arg_keys        which arguments were supplied (presence, not value)
//                context.arg_text        every string in the call, lowercased — for `like`
//                context.principal / .role / .tenant / .upstream / .tool
//
// Give every rule an @id: it is the name that appears in the audit ledger when the rule fires.

// ---------------------------------------------------------------------------------------------
// Roles: who may do what kind of thing at all.
// ---------------------------------------------------------------------------------------------

// admin: full access to every governed tool.
@id("admin-full-access")
permit (
  principal in Role::"admin",
  action,
  resource
);

// operator: may call any tool. Writes are still held for a person (product.yaml approval).
@id("operator-may-call-any-tool")
permit (
  principal in Role::"operator",
  action,
  resource
);

// readonly: may call READ tools only. Writes are denied here regardless of approval.
@id("readonly-may-read")
permit (
  principal in Role::"readonly",
  action == Action::"read",
  resource
);

// approver: deliberately absent. Someone who releases other people's writes should not also be
// making tool calls, so no permit names this role and Cedar's default-deny does the rest — an
// approver's own call is denied, and the ledger records it. Who may APPROVE is a separate list
// (product.yaml approval.approver_roles), because approving is not a tool call.

// ---------------------------------------------------------------------------------------------
// Guardrails: things nobody may do, whatever their role, because the ARGUMENTS say what it is.
//
// These are the rules a role check alone can never express. Each one below is a real control an
// enterprise already has on paper; delete the ones you do not want and write your own — the
// attributes above are all you need. A `forbid` beats every `permit`, including admin's.
// ---------------------------------------------------------------------------------------------

// Nothing writes to the default branch. Ship through a pull request like everyone else.
@id("no-writes-to-the-default-branch")
forbid (
  principal,
  action == Action::"write",
  resource
) when {
  context has branch && (context.branch == "main" || context.branch == "master")
};

// No destructive SQL through an assistant, in any argument, on any server. `arg_text` is every
// string in the call, so this catches the query wherever the server decided to put it.
@id("no-destructive-sql")
forbid (
  principal,
  action,
  resource
) when {
  context has arg_text &&
  (context.arg_text like "*drop table*" ||
   context.arg_text like "*drop database*" ||
   context.arg_text like "*truncate *" ||
   context.arg_text like "*delete from*")
};

// The customer table is not something an assistant edits, whoever is asking.
@id("no-writes-to-customer-data")
forbid (
  principal,
  action == Action::"write",
  resource
) when {
  context has table && (context.table == "customers" || context.table == "payments")
};

// Mail goes to colleagues. Sending company data to an outside address is the exfiltration path
// that matters most, and it is one attribute away from being unwatched. Replace the domain with
// yours — everything not listed counts as outside.
@id("no-mail-to-outside-addresses")
forbid (
  principal,
  action == Action::"write",
  resource
) when {
  context has domains &&
  context.domains.containsAny(["gmail.com", "outlook.com", "proton.me", "external.example"])
};

// A production secret store is readable by the assistant, never writable by it.
@id("no-writes-to-secrets")
forbid (
  principal,
  action == Action::"write",
  resource
) when {
  context has path && (context.path like "*/secrets/*" || context.path like "*.env*")
};

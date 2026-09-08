// gatekeeper.cedar — policy-as-code (RBAC allow/deny per role x tool).
// Cedar is deterministic and analyzable: this file IS the authorization contract (ADR-002).
// Principals are roles (readonly | operator | admin); Actions are MCP tool calls;
// Resources are upstream tools "<upstream>::<tool>". Default decision = deny (fail-closed).

// admin: full access to every governed tool.
permit (
  principal in Role::"admin",
  action,
  resource
);

// operator: may call any tool. (Writes still get risk-scored + human-approved in M2.)
permit (
  principal in Role::"operator",
  action,
  resource
);

// readonly: may call READ tools only. Writes are denied here regardless of approval.
permit (
  principal in Role::"readonly",
  action == Action::"read",
  resource
);

// approver: deliberately absent. Someone who releases other people's writes should not also be
// making tool calls, so no permit names this role and Cedar's default-deny does the rest — an
// approver's own call is denied, and the ledger records it. Who may APPROVE is a separate list
// (product.yaml approval.approver_roles), because approving is not a tool call.

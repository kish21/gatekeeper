# One afternoon with GateKeeper

*Everything on this page is pasted from a real run. Nothing is mocked. You can reproduce it in
ten minutes with the commands shown, with or without an AI assistant installed.*

## The situation

Priya runs operations at a small company. The team has an AI assistant that can read and write
the shared files. It is fast and useful, and it makes Priya nervous, because it can also change
things. She has three questions she cannot answer today:

1. When the assistant changes something, who is that change attributed to?
2. What is it allowed to change, and who decides?
3. Afterwards, can she prove what happened, in a way nobody can quietly edit?

GateKeeper is a small program that sits between the assistant and the files. Here is what
happened the afternoon Priya installed it.

## 1. Setup, two commands

```text
$ gatekeeper init
+----------------------------------------------------------------------------------------+
| secrets file     | /home/priya/gatekeeper/.env  (wrote GATEKEEPER_HMAC_KEY,            |
|                  | GATEKEEPER_AGENT_TOKEN)                                             |
| audit ledger     | /home/priya/gatekeeper/.gatekeeper/audit.db  (0 entries, intact)    |
| demo sandbox     | /home/priya/gatekeeper/.gatekeeper/demo_sandbox (welcome.txt)       |
| governed servers | demo-files, time                                                    |
+----------------------------------------------------------------------------------------+
Ready. Next: gatekeeper doctor prints the config to paste into your MCP host.
```

`init` made a secret key for the audit trail, picked a badge for the assistant, and created an
empty ledger. Then:

```text
$ gatekeeper doctor
+--------------------+--------+------------------------------------------------------+
| check              | status | detail                                               |
|--------------------+--------+------------------------------------------------------|
| HMAC key           | OK     | set (chain key, validated)                           |
| audit ledger       | OK     | .gatekeeper/audit.db (0 entries, chain intact)       |
| policy             | OK     | policies parses                                      |
| agent token        | OK     | alice (operator) for stdio                           |
| server: demo-files | OK     | module examples.demo_file_server (project)           |
| server: time       | OK     | module mcp_server_time found                         |
+--------------------+--------+------------------------------------------------------+
Paste this into your MCP host (Claude Desktop: claude_desktop_config.json):
{
  "mcpServers": {
    "gatekeeper": {
      "command": "/home/priya/gatekeeper/.venv/bin/gatekeeper",
      "args": ["serve"],
      "env": { "GATEKEEPER_CONFIG_DIR": "/home/priya/gatekeeper/config" }
    }
  }
}
```

Priya pastes that block into her assistant's settings and restarts it. From now on the
assistant talks to GateKeeper, and GateKeeper talks to the files. The assistant does not know
the difference.

> **No assistant installed?** The repository ships a stand-in. `python -m scripts.agent ...`
> makes one tool call through the real gateway, exactly the way an assistant would. Every
> "assistant" line below was produced with it.

## 2. The assistant sees the tools, and a read just works

```text
$ python -m scripts.agent list
  read_file            Read a UTF-8 text file from the demo sandbox.
  list_dir             List entry names in a sandbox directory.
  write_file           Write (create/overwrite) a UTF-8 text file in the sandbox.
  delete_file          Delete a file in the sandbox.
  get_current_time     Get current time in a specific timezone
  convert_time         Convert time between timezones
```

Two servers, six tools, all behind the guard. Someone asks the assistant to read the welcome
note:

```text
$ python -m scripts.agent read_file path=welcome.txt
assistant -> read_file {"path": "welcome.txt"}
gateway   <- OK: Hello from GateKeeperAI. This file is served by the governed demo_file_server...
```

Nothing visible changed for the assistant. Behind the scenes GateKeeper checked the badge,
checked the rulebook, wrote a record, and let the read through. Reads are never held up.

## 3. A write is held until a human says yes

Someone asks the assistant to write a note: "Meeting moved to 3pm". The assistant calls
`write_file`. This time it waits. On Priya's side, a request has appeared:

```text
$ gatekeeper pending
                              writes waiting for a human
+----------+-------------+-------+----------+-----------------------+------------------------+
| id       | since (UTC) | who   | role     | tool                  | arguments              |
|----------+-------------+-------+----------+-----------------------+------------------------|
| ea15e33b | 11:48:25    | alice | operator | demo-files:write_file | {"content": "Meeting   |
|          |             |       |          |                       | moved to 3pm",         |
|          |             |       |          |                       | "path": "notes.txt"}   |
+----------+-------------+-------+----------+-----------------------+------------------------+
Decide with: gatekeeper approve <id>   or   gatekeeper deny <id> --reason '...'
```

She can see exactly what the assistant wants to do, on whose behalf, before it happens. The
ticket about that meeting is still open, so she says no:

```text
$ gatekeeper deny ea15e33b --reason "not while the ticket is still open"
DENIED request ea15e33b: alice -> demo-files:write_file (by priya)
```

The assistant, which has been waiting, gets an answer it can relay to the person who asked:

```text
assistant -> write_file {"path": "notes.txt", "content": "Meeting moved to 3pm"}
gateway   <- ERROR: denied: denied by priya (request ea15e33b): not while the ticket is still open
```

The file was never touched. The file server was never even called.

If nobody had answered, the request would have expired on its own after ninety seconds, and
that counts as a no. If the assistant had given up waiting, the request would have been
cancelled, so a late approval can never execute something nobody is watching.

## 4. Second attempt, approved

The ticket gets closed. The assistant is asked again, the request appears again, and this time
Priya approves:

```text
$ gatekeeper approve 96a1e4bc
APPROVED request 96a1e4bc: alice -> demo-files:write_file (by priya)
```

```text
assistant -> write_file {"path": "notes.txt", "content": "Meeting moved to 3pm"}
gateway   <- OK: wrote 20 bytes to notes.txt
```

Now the file exists. Priya's name is on the decision that allowed it.

## 5. The record

Later that day, Priya looks at what the assistant did:

```text
$ gatekeeper tail --with-id
+-----+--------------+---------------------+-----------+-----------------------+---------+
| seq | call_id      | ts                  | principal | tool                  | verdict |
|-----+--------------+---------------------+-----------+-----------------------+---------|
| 1   | 456dc7466200 | 2026-09-08T11:48:23 | alice     | demo-files:read_file  | allow   |
| 2   | 456dc7466200 | 2026-09-08T11:48:23 | alice     | demo-files:read_file  | allow   |
| 3   | 82338b8c6237 | 2026-09-08T11:48:25 | alice     | demo-files:write_file | pending |
| 4   | 82338b8c6237 | 2026-09-08T11:48:29 | alice     | demo-files:write_file | deny    |
| 5   | d527b74b86a6 | 2026-09-08T11:48:32 | alice     | demo-files:write_file | pending |
| 6   | d527b74b86a6 | 2026-09-08T11:48:35 | alice     | demo-files:write_file | allow   |
| 7   | d527b74b86a6 | 2026-09-08T11:48:35 | alice     | demo-files:write_file | allow   |
+-----+--------------+---------------------+-----------+-----------------------+---------+
```

Every call is there: the read, the write that was held and denied, the write that was held,
approved, and carried out. One call in detail:

```text
$ gatekeeper show 82338b8c
+---------------+-------------------------------------------+
| principal     | alice (role=operator, tenant=default)     |
| tool          | demo-files:write_file                     |
| action        | write                                     |
| final verdict | deny                                      |
+---------------+-------------------------------------------+
                        what happened, in order
+-----+---------------------+---------+---------------------------------------------------+
| seq | ts (UTC)            | verdict | reason                                            |
|-----+---------------------+---------+---------------------------------------------------|
| 3   | 2026-09-08T11:48:25 | pending | write held for human approval (allowed by cedar   |
|     |                     |         | policy: role 'operator' may write ...)            |
| 4   | 2026-09-08T11:48:29 | deny    | denied by priya (request ea15e33b): not while the |
|     |                     |         | ticket is still open                              |
+-----+---------------------+---------+---------------------------------------------------+
```

That answers Priya's first two questions. The change was attributed to the assistant's badge
(alice, an operator). The rulebook allowed the write, and a named human decided whether it
happened, with the reason kept.

## 6. Prove nobody edited the record

The third question. Each record carries a keyed hash of itself and of the record before it,
so the ledger is a chain. Checking it is one command:

```text
$ gatekeeper verify
OK ledger intact - 7 entries verified
head: 8aa8f5d9feb26f409a6c412e328ea29afa6759f149bc9aef41df0e49e60533af
```

To see what the check is worth, Priya makes a copy of the ledger and edits one record in it,
changing the denial to say it was approved. On the copy:

```text
$ gatekeeper verify
TAMPERED broken at seq=4: entry_hash mismatch (record altered or wrong key)
(verified 3 before the break)
```

The check fails and points at the exact record. Anyone who edits a record, inserts one, or
removes one from the middle breaks the chain. The `head` hash printed by a clean run can be
kept somewhere else, such as in a ticket, and passed back later with `--expect-head`, which
also catches records removed from the end.

## What Priya has now

| Her question | The answer she can give |
|---|---|
| Who is the AI acting as? | Every record names the badge and the role. Unknown badges are refused before anything else happens. |
| What is it allowed to do? | Reads go through. Writes wait for a named human, or a read-only badge is refused outright. Both are recorded with the reason. |
| What did it actually do? | A chained ledger with a one-command check that fails loudly at the exact record if anyone tampers with it. |

## Do it yourself

```bash
git clone https://github.com/kish21/gatekeeper && cd gatekeeper
make install && source .venv/bin/activate      # .venv\Scripts\activate on Windows
gatekeeper init
gatekeeper doctor                              # paste the JSON into your assistant, or use scripts/agent
```

Then, in one terminal, act as the assistant:

```bash
python -m scripts.agent read_file path=welcome.txt
python -m scripts.agent write_file path=notes.txt content="Meeting moved to 3pm"
```

and in another, act as Priya:

```bash
gatekeeper pending
gatekeeper deny <id> --reason "not yet"        # or: gatekeeper approve <id>
gatekeeper tail --with-id
gatekeeper show <id>
gatekeeper verify
```

To govern your own tools instead of the demo files, add them to `config/upstreams.yaml`. See
[Getting started](getting-started.md). Who may do what is in `policies/gatekeeper.cedar`; which
writes are held is in `config/product.yaml`.

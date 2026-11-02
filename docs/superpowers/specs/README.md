# The mcp-kb spec

What the server does, one area per file. Each requirement is numbered, says one thing, and is
true of the code unless it's marked *(proposed)*. There's no history here: how a requirement came
to be is in [the plans](../plans/), and how to install and use the server is in
[the wiki](https://github.com/kubed-io/mcp-kb/wiki).

| Area | IDs | Covers |
|---|---|---|
| [Config and sources](config-and-sources.md) | CFG, SRC | The config file, credentials, sources and their refs, caching, refresh and reindex, startup failures |
| [Plugins and libraries](plugins-and-libraries.md) | PLG, LIB | Declaring plugins, reading `plugin.json` and marketplaces, libraries and selectors, descriptions, conflicts between plugins |
| [Skills](skills.md) | SKL | What a skill is, skill addresses, indexes and manifests, library files, the resource prefix, live reads, the MCP Skills extension |
| [Prompts](prompts.md) | PRM | The three dialects, arguments, naming, placeholders, elicitation |
| [Scoping and instructions](scoping-and-instructions.md) | SCP, INS | Library, category and tag selection, refusals, the server instructions a scope gets |
| [HTTP and tools](http-and-tools.md) | HTTP, TOOL | `/mcp`, `/health`, `/reindex`, the OpenAPI document, protocol eras, the container, the tool mirrors |
| [Agents](agents.md) | AGT | Plugin agents through the draft agents extension *(all proposed)* |

## Rules for this folder

- **A behaviour change updates its spec file in the same pull request.** Add, reword or mark
  requirements. IDs are stable: a removed requirement leaves a gap, and a number is never reused.
- **Proposed work is written here as *(proposed)*** and loses the mark when it ships. A proposed
  requirement that replaces a built one says which.
- **Statements only.** No dates, issue numbers or "used to". Why a requirement exists, and what it
  replaced, belongs in the dated design in [plans/](../plans/).
- **Public repo:** no hostnames or personal names. The maintainer is Dr K; examples use
  `example.com`.

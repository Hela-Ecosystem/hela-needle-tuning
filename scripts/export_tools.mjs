// Export an MCP server's tools/list to JSON for scripts/refresh_catalog.py.
//
//   node scripts/export_tools.mjs <out.json> [--cwd <dir>] -- <command> [args...]
//
// Examples (the MCP SDK is taken from a HeLa runtime install, or set MCP_SDK to any
// node_modules/@modelcontextprotocol/sdk directory):
//   whole runtime, one profile:   HELA_PROFILE=dev-workspace node scripts/export_tools.mjs live.json -- node <runtime>/dist/index.js
//   one cell (bare tool names):   node scripts/export_tools.mjs receptor.json --cwd <scrcpy-mcp> -- node dist/server.js
//
// Output: [{name, description, parameters}]. The server is started with your environment, so
// run it where the cell's own dependencies exist; cells whose runtime dependencies are missing
// (for example a device or Blender) can usually still be listed.
import fs from 'node:fs';

const sdk = process.env.MCP_SDK
  || `${process.env.HELA_RUNTIME_ROOT || `${process.env.HOME}/.local/share/hela/installations/servy-runtime/hela-runtime`}/node_modules/@modelcontextprotocol/sdk`;
const { Client } = await import(`${sdk}/dist/esm/client/index.js`);
const { StdioClientTransport } = await import(`${sdk}/dist/esm/client/stdio.js`);

const argv = process.argv.slice(2);
const split = argv.indexOf('--');
if (split < 1) { console.error('usage: export_tools.mjs <out.json> [--cwd <dir>] -- <command> [args...]'); process.exit(2); }
const out = argv[0];
const cwdAt = argv.indexOf('--cwd');
const cwd = cwdAt >= 0 && cwdAt < split ? argv[cwdAt + 1] : undefined;
const [command, ...args] = argv.slice(split + 1);

const client = new Client({ name: 'tools-export', version: '0' }, { capabilities: {} });
await client.connect(new StdioClientTransport({ command, args, cwd, env: { ...process.env } }));
const { tools } = await client.listTools();
const list = tools.map((t) => ({ name: t.name, description: t.description || '', parameters: t.inputSchema || { type: 'object', properties: {} } }));
fs.writeFileSync(out, JSON.stringify(list));
console.log(`wrote ${list.length} tools to ${out}`);
await client.close();
process.exit(0);

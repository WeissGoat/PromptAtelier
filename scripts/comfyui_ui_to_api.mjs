// 把 ComfyUI 的 UI 工作流（界面保存的 JSON）转成 API 工作流，等同于界面上的 Export (API)。
//
// 转换器来自 comfyui-mcp（MIT，和 Codex 里配的 comfyui-local MCP 是同一个包、同一个版本），
// 它的 get_workflow 工具就是这样转的：处理 bypass / mute、Reroute、PrimitiveNode、seed 后面的
// control_after_generate 隐藏控件。需要一个运行中的 ComfyUI 提供 /object_info（本机 aki 即可，不出图）。
//
// 用法（仓库根目录）：
//   npx -y -p comfyui-mcp@0.49.4 -c "node scripts/comfyui_ui_to_api.mjs <ui.json> <api.json> [--url http://127.0.0.1:8188]"
//
// 和手动导出的差别：界面扩展的显示控件（speak_and_recognation、ShowText 的显示文本）不导出，后端不读它们。
// 转换器遇到本机没有的下拉值时会换成第一个可选值；这里改回工作流里写的值（和手动导出一致），并列出来。
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

function usage(message) {
  if (message) console.error(message);
  console.error("usage: node scripts/comfyui_ui_to_api.mjs <ui.json> <api.json> [--url http://127.0.0.1:8188]");
  process.exit(2);
}

/** npx -p 把包的 node_modules/.bin 放进 PATH；从那里找到 comfyui-mcp 的转换器。 */
function findConverter() {
  for (const entry of (process.env.PATH ?? "").split(path.delimiter)) {
    if (path.basename(entry) !== ".bin") continue;
    const candidate = path.join(entry, "..", "comfyui-mcp", "dist", "services", "workflow-converter.js");
    if (fs.existsSync(candidate)) return candidate;
  }
  usage('comfyui-mcp not found; run through: npx -y -p comfyui-mcp@0.49.4 -c "node scripts/comfyui_ui_to_api.mjs ..."');
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

const args = process.argv.slice(2);
const urlIndex = args.indexOf("--url");
const baseUrl = (urlIndex >= 0 ? args.splice(urlIndex, 2)[1] : "http://127.0.0.1:8188").replace(/\/+$/, "");
const [input, output] = args;
if (!input || !output) usage();

const { convertUiToApi, collectNodeTypes, isUiFormat } = await import(pathToFileURL(findConverter()).href);
const ui = JSON.parse(fs.readFileSync(input, "utf8"));
if (!isUiFormat(ui)) usage(`${input} is not a UI workflow (already API format?)`);

let objectInfo;
try {
  objectInfo = await fetchJson(`${baseUrl}/object_info`);
} catch (error) {
  usage(`cannot read ${baseUrl}/object_info — start ComfyUI first (${error.message})`);
}
// 和 MCP 的 backfillObjectInfo 一样：批量 /object_info 漏掉的节点类单独查一次。
for (const type of new Set(collectNodeTypes(ui))) {
  if (!type || type in objectInfo) continue;
  try {
    Object.assign(objectInfo, await fetchJson(`${baseUrl}/object_info/${encodeURIComponent(type)}`));
  } catch {
    // 查不到的留给下面的 missing 检查报出来。
  }
}

const { workflow, warnings } = convertUiToApi(ui, objectInfo);
const restored = [];
const otherWarnings = [];
const substitution = /^Node (\S+) \(([^)]*)\): widget "([^"]+)" value "((?:[^"\\]|\\.)*)" is not a valid option .*substituting/;
for (const warning of warnings ?? []) {
  const match = substitution.exec(warning);
  if (match && workflow[match[1]]?.inputs) {
    const declared = JSON.parse(`"${match[4]}"`);
    workflow[match[1]].inputs[match[3]] = declared;
    restored.push(`${match[1]} ${match[2]}.${match[3]} = ${declared}`);
  } else {
    otherWarnings.push(warning);
  }
}

const activeTypes = new Set(ui.nodes.filter((node) => node.mode !== 2 && node.mode !== 4).map((node) => node.type));
const missing = [...activeTypes].filter((type) => !["Reroute", "Note", "MarkdownNote", "PrimitiveNode"].includes(type) && !(type in objectInfo));

fs.mkdirSync(path.dirname(path.resolve(output)), { recursive: true });
fs.writeFileSync(output, `${JSON.stringify(workflow, null, 2)}\n`);
console.log(`wrote ${output}: ${Object.keys(workflow).length} nodes`);
if (restored.length) console.log(`kept declared values not installed on ${baseUrl}:\n  ${restored.join("\n  ")}`);
if (otherWarnings.length) console.log(`converter warnings:\n  ${otherWarnings.join("\n  ")}`);
if (missing.length) {
  console.error(`node types unknown to ${baseUrl} (missing custom nodes?): ${missing.join(", ")}`);
  process.exit(1);
}

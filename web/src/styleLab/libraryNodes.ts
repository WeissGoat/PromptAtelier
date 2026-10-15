/** 素材库节点（角色/动作卡片）的前端缓存：同一个节点页面里只读一次。 */
import type { LibraryNode, MaterialRole } from "./api";
import { getLibraryNode } from "./api";

const nodeCache = new Map<string, Promise<LibraryNode>>();

export function loadNode(ref: string, role: MaterialRole): Promise<LibraryNode> {
  const key = `${role}:${ref}`;
  if (!nodeCache.has(key)) {
    const promise = getLibraryNode(ref, role).catch((error) => {
      nodeCache.delete(key);
      throw error;
    });
    nodeCache.set(key, promise);
  }
  return nodeCache.get(key)!;
}

/** 节点的全部 tag（按部位顺序，去重）。 */
export function nodeTags(node: LibraryNode): string[] {
  return [...new Set(node.sections.flatMap((section) => section.tags))];
}

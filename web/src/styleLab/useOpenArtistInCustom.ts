import { useCallback } from "react";

import { apiGet } from "../api/client";
import type { NodeReadResponse } from "../api/types";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import type { ArtistExport } from "./api";

/** 读回导出的 artist 节点，放进 Custom 的主画风槽，然后跳到 Custom。 */
export function useOpenArtistInCustom(onOpenCustom?: () => void) {
  const workspace = useCustomWorkspace();

  return useCallback(
    async (artist: ArtistExport) => {
      const response = await apiGet<NodeReadResponse>(
        `/nodes/read?${new URLSearchParams({ ref: artist.path, role: "artist" }).toString()}`,
      );
      workspace.selectNode(
        workspace.state.groups.artist.primary.slotId,
        response.ref,
        response.node,
        response.editor,
      );
      workspace.closeEditor();
      if (onOpenCustom) onOpenCustom();
      else if (typeof window !== "undefined") window.location.hash = "#/custom";
    },
    [workspace, onOpenCustom],
  );
}

import { useState } from "react";

import type { NodeSummary } from "../api/types";
import { NodePicker } from "./NodePicker";

type ArtistRefPickerProps = {
  label: string;
  value: string;
  onChange: (ref: string) => void;
};

/** 复用普通节点搜索，只把选中的 Artist ref 留在 Prompt Behavior 中。 */
export function ArtistRefPicker({ label, value, onChange }: ArtistRefPickerProps) {
  const [selectedName, setSelectedName] = useState("");
  const [selectedRef, setSelectedRef] = useState("");
  const displayValue = selectedRef === value ? selectedName : value;

  function selectArtist(node: NodeSummary) {
    setSelectedRef(node.ref);
    setSelectedName(node.name);
    onChange(node.ref);
  }

  function clearArtist() {
    setSelectedRef("");
    setSelectedName("");
    onChange("");
  }

  return (
    <NodePicker
      displayValue={displayValue}
      label={label}
      onClear={clearArtist}
      onSelect={selectArtist}
      placeholder="搜索 Vibe Artist"
      role="artist"
      value={value}
    />
  );
}

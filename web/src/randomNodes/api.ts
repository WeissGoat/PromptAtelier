import { apiGet, apiPost } from "../api/client";
import type {
  NodePoolCollectionsResponse,
  NodePoolSampleResponse,
  NodePoolScanRequest,
  NodePoolScanResponse,
} from "../api/types";
import type { NodePoolSpec } from "../workspace/types";

export function listNodePoolCollections(role: string): Promise<NodePoolCollectionsResponse> {
  return apiGet(`/node-pools/collections?role=${encodeURIComponent(role)}`);
}

export function scanNodePool(request: NodePoolScanRequest): Promise<NodePoolScanResponse> {
  return apiPost("/node-pools/scan", request);
}

export function sampleNodePool(role: string, spec: NodePoolSpec, count: number): Promise<NodePoolSampleResponse> {
  return apiPost("/node-pools/sample", { role, spec, count });
}

import { useCallback, useEffect, useState } from "react";

import type { HistoryNodeFilter } from "./api/types";
import { Layout, type PageKey } from "./components/Layout";
import { buildHistoryHash, parseHistoryHashNodes } from "./history/historyFilter";
import { AgentStudio } from "./pages/AgentStudio";
import { CompareStudio } from "./pages/CompareStudio";
import { CustomStudio } from "./pages/CustomStudio";
import { HistoryPage } from "./pages/HistoryPage";
import { StyleLabErrorBoundary } from "./styleLab/StyleLabErrorBoundary";
import { StyleLabPage } from "./styleLab/StyleLabPage";
import { CustomWorkspaceProvider } from "./workspace/CustomWorkspaceProvider";
import { useOpenImageNodeInCustom } from "./workspace/useOpenImageNodeInCustom";
import "./styles.css";
import "./styles/custom.css";

const PAGE_STORAGE_KEY = "promptatelier.active-page/v1";
const PAGE_KEYS: readonly PageKey[] = ["custom", "agent", "results", "compare", "style-lab"];

function isPageKey(value: string | null): value is PageKey {
  return value !== null && (PAGE_KEYS as readonly string[]).includes(value);
}

function pageKeyFromHash(hash: string): PageKey | null {
  const rawHash = hash.replace(/^#\/?/, "").split("?")[0] ?? "";
  return isPageKey(rawHash) ? rawHash : null;
}

function getInitialPage(): PageKey {
  if (typeof window !== "undefined") {
    const hashPage = pageKeyFromHash(window.location.hash);
    if (hashPage) {
      return hashPage;
    }
    const saved = window.localStorage?.getItem(PAGE_STORAGE_KEY) ?? null;
    if (isPageKey(saved)) {
      return saved;
    }
  }
  return "custom";
}

function AppContent() {
  const [page, setPage] = useState<PageKey>(getInitialPage);
  const [historyFilterRequest, setHistoryFilterRequest] = useState<{ nodes: HistoryNodeFilter[]; seq: number } | null>(() => {
    if (typeof window === "undefined") return null;
    const nodes = parseHistoryHashNodes(window.location.hash);
    return nodes.length ? { nodes, seq: 1 } : null;
  });

  const handlePageChange = useCallback((nextPage: PageKey) => {
    setPage(nextPage);
    if (typeof window !== "undefined") {
      window.location.hash = `#/${nextPage}`;
      window.localStorage?.setItem(PAGE_STORAGE_KEY, nextPage);
    }
  }, []);

  const handleOpenHistoryForNode = useCallback((node: HistoryNodeFilter) => {
    const normalized: HistoryNodeFilter = {
      role: node.role.trim().toLowerCase(),
      name: node.name.trim(),
      ref: node.ref?.trim() || null,
    };
    const nodes = [normalized];
    setHistoryFilterRequest((prev) => ({ nodes, seq: (prev?.seq ?? 0) + 1 }));
    setPage("results");
    if (typeof window !== "undefined") {
      window.location.hash = buildHistoryHash(nodes);
      window.localStorage?.setItem(PAGE_STORAGE_KEY, "results");
    }
  }, []);

  const openImageNodeInCustom = useOpenImageNodeInCustom(() => handlePageChange("custom"));

  useEffect(() => {
    function onHashChange() {
      const nextPage = pageKeyFromHash(window.location.hash);
      if (nextPage) {
        setPage(nextPage);
        if (nextPage === "results") {
          const nodes = parseHistoryHashNodes(window.location.hash);
          if (nodes.length) {
            setHistoryFilterRequest((prev) => ({ nodes, seq: (prev?.seq ?? 0) + 1 }));
          }
        }
      }
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const content = {
    agent: <AgentStudio />,
    custom: <CustomStudio onOpenHistory={handleOpenHistoryForNode} onOpenNode={openImageNodeInCustom} />,
    results: (
      <HistoryPage
        externalFilterRequest={historyFilterRequest}
        onOpenNode={openImageNodeInCustom}
      />
    ),
    compare: <CompareStudio onOpenNode={openImageNodeInCustom} />,
    "style-lab": (
      <StyleLabErrorBoundary>
        <StyleLabPage onOpenCustom={() => handlePageChange("custom")} />
      </StyleLabErrorBoundary>
    ),
  }[page];

  return (
    <Layout onPageChange={handlePageChange} page={page}>
      {content}
    </Layout>
  );
}

export function App() {
  return (
    <CustomWorkspaceProvider>
      <AppContent />
    </CustomWorkspaceProvider>
  );
}

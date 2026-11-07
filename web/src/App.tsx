import { useEffect, useState } from "react";

import { Layout, type PageKey } from "./components/Layout";
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

function getInitialPage(): PageKey {
  if (typeof window !== "undefined") {
    const rawHash = window.location.hash.replace(/^#\/?/, "");
    if (isPageKey(rawHash)) {
      return rawHash;
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

  const handlePageChange = (nextPage: PageKey) => {
    setPage(nextPage);
    if (typeof window !== "undefined") {
      window.location.hash = `#/${nextPage}`;
      window.localStorage?.setItem(PAGE_STORAGE_KEY, nextPage);
    }
  };

  const openImageNodeInCustom = useOpenImageNodeInCustom(() => handlePageChange("custom"));

  useEffect(() => {
    function onHashChange() {
      const rawHash = window.location.hash.replace(/^#\/?/, "");
      if (isPageKey(rawHash)) {
        setPage(rawHash);
      }
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const content = {
    agent: <AgentStudio />,
    custom: <CustomStudio onOpenNode={openImageNodeInCustom} />,
    results: <HistoryPage onOpenNode={openImageNodeInCustom} />,
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

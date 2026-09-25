import { useEffect, useState } from "react";

import { Layout, type PageKey } from "./components/Layout";
import { BatchStudio } from "./pages/BatchStudio";
import { CompareStudio } from "./pages/CompareStudio";
import { CustomStudio } from "./pages/CustomStudio";
import { ResultsGallery } from "./pages/ResultsGallery";
import { CustomWorkspaceProvider } from "./workspace/CustomWorkspaceProvider";
import "./styles.css";

const PAGE_STORAGE_KEY = "promptatelier.active-page/v1";

function getInitialPage(): PageKey {
  if (typeof window !== "undefined") {
    const rawHash = window.location.hash.replace(/^#\/?/, "");
    if (rawHash === "custom" || rawHash === "batch" || rawHash === "results" || rawHash === "compare") {
      return rawHash;
    }
    const saved = window.localStorage?.getItem(PAGE_STORAGE_KEY) as PageKey;
    if (saved === "custom" || saved === "batch" || saved === "results" || saved === "compare") {
      return saved;
    }
  }
  return "custom";
}

export function App() {
  const [page, setPage] = useState<PageKey>(getInitialPage);

  const handlePageChange = (nextPage: PageKey) => {
    setPage(nextPage);
    if (typeof window !== "undefined") {
      window.location.hash = `#/${nextPage}`;
      window.localStorage?.setItem(PAGE_STORAGE_KEY, nextPage);
    }
  };

  useEffect(() => {
    function onHashChange() {
      const rawHash = window.location.hash.replace(/^#\/?/, "");
      if (rawHash === "custom" || rawHash === "batch" || rawHash === "results" || rawHash === "compare") {
        setPage(rawHash);
      }
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const content = {
    custom: <CustomStudio />,
    batch: <BatchStudio />,
    results: <ResultsGallery />,
    compare: <CompareStudio />,
  }[page];

  return (
    <CustomWorkspaceProvider>
      <Layout onPageChange={handlePageChange} page={page}>
        {content}
      </Layout>
    </CustomWorkspaceProvider>
  );
}

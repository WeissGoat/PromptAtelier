import { useState } from "react";

import { Layout, type PageKey } from "./components/Layout";
import { BatchStudio } from "./pages/BatchStudio";
import { CustomStudio } from "./pages/CustomStudio";
import { ResultsGallery } from "./pages/ResultsGallery";
import { CustomWorkspaceProvider } from "./workspace/CustomWorkspaceProvider";
import "./styles.css";

export function App() {
  const [page, setPage] = useState<PageKey>("custom");
  const content = {
    custom: <CustomStudio />,
    batch: <BatchStudio />,
    results: <ResultsGallery />,
  }[page];

  return (
    <CustomWorkspaceProvider>
      <Layout onPageChange={setPage} page={page}>
        {content}
      </Layout>
    </CustomWorkspaceProvider>
  );
}

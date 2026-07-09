import { useState } from "react";

import { Layout, type PageKey } from "./components/Layout";
import { BatchStudio } from "./pages/BatchStudio";
import { CompareStudio } from "./pages/CompareStudio";
import { CustomStudio } from "./pages/CustomStudio";
import { ResultsGallery } from "./pages/ResultsGallery";
import "./styles.css";

export function App() {
  const [page, setPage] = useState<PageKey>("custom");
  const content = {
    custom: <CustomStudio />,
    compare: <CompareStudio />,
    batch: <BatchStudio />,
    results: <ResultsGallery />,
  }[page];

  return (
    <Layout onPageChange={setPage} page={page}>
      {content}
    </Layout>
  );
}

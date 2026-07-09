import { useState } from "react";

import { Layout, type PageKey } from "./components/Layout";
import { CustomStudio } from "./pages/CustomStudio";
import "./styles.css";

function PlaceholderPage({ title }: { title: string }) {
  return (
    <main className="page-panel">
      <section className="panel">
        <div className="panel-title">
          <h2>{title}</h2>
        </div>
      </section>
    </main>
  );
}

export function App() {
  const [page, setPage] = useState<PageKey>("custom");
  const content =
    page === "custom" ? <CustomStudio /> : <PlaceholderPage title={`${page[0].toUpperCase()}${page.slice(1)}`} />;

  return (
    <Layout onPageChange={setPage} page={page}>
      {content}
    </Layout>
  );
}

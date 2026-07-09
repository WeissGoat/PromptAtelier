import { Copy, Eye } from "lucide-react";
import { useState } from "react";

export function CompareStudio() {
  const [baseArtist, setBaseArtist] = useState("20260412");
  const [variantArtist, setVariantArtist] = useState("20260412_2");
  const [prompt, setPrompt] = useState("1girl, standing");

  return (
    <main className="page-panel compare-page">
      <section className="panel">
        <div className="panel-title">
          <h2>Compare Studio</h2>
        </div>
        <label className="field">
          <span>Shared Prompt</span>
          <textarea aria-label="Shared Prompt" onChange={(event) => setPrompt(event.target.value)} value={prompt} />
        </label>
        <div className="params-grid">
          <label className="field">
            <span>Base Artist</span>
            <input aria-label="Base Artist" onChange={(event) => setBaseArtist(event.target.value)} value={baseArtist} />
          </label>
          <label className="field">
            <span>Variant Artist</span>
            <input aria-label="Variant Artist" onChange={(event) => setVariantArtist(event.target.value)} value={variantArtist} />
          </label>
        </div>
        <div className="button-row">
          <button type="button">
            <Copy size={16} />
            Mirror
          </button>
          <button type="button">
            <Eye size={16} />
            Preview
          </button>
        </div>
      </section>
      <section className="panel">
        <div className="panel-title">
          <h2>Variants</h2>
        </div>
        <pre className="json-preview">
          {JSON.stringify(
            [
              { artist: baseArtist, prompt },
              { artist: variantArtist, prompt },
            ],
            null,
            2,
          )}
        </pre>
      </section>
    </main>
  );
}

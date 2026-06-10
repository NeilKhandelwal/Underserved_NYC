export function AskPlaceholder() {
  return (
    <div className="ask-placeholder">
      <div className="ask-badge">Coming soon</div>
      <h2>Ask about an outlier</h2>
      <p className="sub" style={{ maxWidth: 560 }}>
        An assistant that helps answer <i>"what policies or factors could explain this
        tract's unexplained neglect?"</i> — grounded in this tool's own tract data,
        cited web search, and NYC housing-policy documents.
      </p>
      <ul className="ask-list">
        <li>Explain why a specific tract scores worse (or better) than its demographics predict</li>
        <li>Compare neighborhoods or council districts and surface shared patterns</li>
        <li>Suggest policy hypotheses with citations — never causal claims</li>
      </ul>
    </div>
  );
}

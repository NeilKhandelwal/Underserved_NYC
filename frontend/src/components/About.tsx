/**
 * About content, written for community and policy leaders (non-technical).
 * The same content is rendered in the "About" tab and in the welcome modal
 * that greets first-time visitors.
 */
export function AboutContent() {
  return (
    <div className="prose">
      <h2>What this map shows</h2>
      <p className="sub">
        A neighborhood-level look at where New York City's housing services fall
        short. Mainly focusing on residuals, where service is worse than demographics
        or income would suggest. 
      </p>

      <h3>The problem with most service maps</h3>
      <p>
        Most maps of housing problems in NYC look like a map of
        poverty: lower-income, majority-minority neighborhoods score worst. That
        is real, but it isn't directly actionable — and it doesn't tell a council member or
        community board <b>where to look next</b>.
      </p>

      <h3>What UnderservedNYC does differently</h3>
      <p>
        Separates two things that usually get blended together:
      </p>
      <ul>
        <li>
          <b>The expected pattern</b> — the well-known reality that poorer
          neighborhoods tend to get slower, thinner housing services.
        </li>
        <li>
          <b>The surprise</b> — neighborhoods getting <b>worse</b> service than
          even their income and demographics would predict. This is the part that
          usually points to how agencies route inspections, close complaints, and
          respond on the ground — not to who lives there.
        </li>
      </ul>
      <p>
        That second number — the surprise, or "unexplained gap" — is the signal
        this tool is built to surface. A high gap is a flag that says{" "}
        <i>worth a closer look</i>, not a verdict.
      </p>

      <h3>What goes into the score</h3>
      <p>
        Each of NYC's ~2,200 census tracts (small neighborhood-sized areas) gets a
        0–100 housing-service score built from public records:
      </p>
      <ul>
        <li>How long 311 housing complaints take to close</li>
        <li>The most serious housing-code violations (HPD Class C)</li>
        <li>Orders that declare buildings unsafe to live in (vacate orders)</li>
      </ul>
      <p>
        Values are adjusted these so that wealthier areas filing more complaints, or one
        slow complaint type, don't distort the picture.
      </p>

      <h3>How to use it</h3>
      <ul>
        <li>
          <b>Map</b> — see every neighborhood; switch the color to the
          "unexplained gap" view to spot the surprises.
        </li>
        <li>
          <b>Watchlist</b> — a ranked, plain-language list of the neighborhoods
          (or council districts) with the biggest gaps, each with a short "why."
        </li>
        <li>
          <b>Demographics &amp; Predictor</b> — explore how income, rent burden,
          and building age relate to service levels.
        </li>
      </ul>

      <h3>What this is — and isn't</h3>
      <p>
        This is a <b>screening and prioritization tool</b>: it tells you where to
        ask questions. It is <b>not</b> proof that any agency is doing anything
        wrong, and it does not make claims about individual buildings or addresses.
        A high gap calls for investigation, not a conclusion.
      </p>
    </div>
  );
}

export function About() {
  return <AboutContent />;
}

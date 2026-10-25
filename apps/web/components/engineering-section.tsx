import {
  engineeringBoundaries,
  modelRoutes,
  runtimeCapabilities,
} from "@/lib/engineering";

const repository = "https://github.com/vishalgwu/tento-agents/blob/main/";
const flow = [
  ["01", "Next.js", "Same-origin server proxies"],
  ["02", "FastAPI", "JWT · RLS · idempotency"],
  ["03", "Supabase", "Saved ticket + durable job"],
  ["04", "LangGraph", "Bounded agent execution"],
  ["05", "Saved result", "Assessment or abstention"],
];

export function EngineeringSection() {
  return (
    <section
      id="engineering"
      className="engineering-section"
      aria-labelledby="engineering-title"
    >
      <div className="section-intro">
        <div>
          <p className="eyebrow">Inside the intelligence</p>
          <h2 id="engineering-title">
            Considered on the outside.
            <br />
            <em>Engineered underneath.</em>
          </h2>
        </div>
        <p>
          A look at the actual implementation: how requests move, where evidence
          enters, and which capabilities are live versus still at the
          code-and-test stage.
        </p>
      </div>
      <div
        className="engineering-stack"
        aria-label="Production technology stack"
      >
        {[
          "Next.js + TypeScript",
          "FastAPI",
          "OpenAI",
          "LangGraph",
          "Supabase / PostgreSQL",
          "Upstash Redis",
          "Vercel",
        ].map((name) => (
          <span key={name}>{name}</span>
        ))}
      </div>
      <ol
        className="architecture-flow"
        aria-label="Production request architecture"
      >
        {flow.map(([number, name, detail]) => (
          <li key={number}>
            <span className="architecture-number">{number}</span>
            <h3>{name}</h3>
            <p>{detail}</p>
          </li>
        ))}
      </ol>
      <p className="engineering-caption">
        FastAPI → PostgreSQL is the durable boundary. Next.js after() starts a
        bounded worker request; pending ticket reads and a protected daily cron
        provide limited recovery. Hobby hosting is not an always-running queue
        consumer.
      </p>
      <div className="engineering-grid">
        {runtimeCapabilities.map((item) => (
          <article key={item.number} className="engineering-card">
            <div className="engineering-card-label">
              <span>{item.tag}</span>
              <span>LIVE PATH</span>
            </div>
            <h3>{item.title}</h3>
            <p>{item.detail}</p>
            <a href={repository + item.source} className="text-link">
              Inspect implementation <span aria-hidden="true">↗</span>
            </a>
          </article>
        ))}
      </div>
      <div className="model-routing">
        <div>
          <p className="eyebrow">One gateway, explicit choices</p>
          <h3>Task routing, without a hidden model switch.</h3>
          <p>
            Current OpenAI deployment mapping. A configured Anthropic model is
            selected only when the OpenAI configuration is absent; it is not a
            request-time failover chain.
          </p>
        </div>
        <div className="routing-table-wrap">
          <table>
            <caption className="sr-only">Current task-to-model routing</caption>
            <thead>
              <tr>
                <th scope="col">Task</th>
                <th scope="col">Logical tier</th>
                <th scope="col">Model</th>
              </tr>
            </thead>
            <tbody>
              {modelRoutes.map((route) => (
                <tr key={route.task}>
                  <th scope="row">{route.task}</th>
                  <td>{route.tier}</td>
                  <td>{route.model}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="engineering-boundaries">
        <h3>Good engineering includes clear boundaries.</h3>
        <p>
          These details are part of the project, with their current maturity
          shown explicitly.
        </p>
        <div className="engineering-detail-grid">
          {engineeringBoundaries.map((item) => (
            <details key={item.title}>
              <summary>
                <span>{item.title}</span>
                <span className="maturity-label">{item.status}</span>
              </summary>
              <p>{item.detail}</p>
              <a href={repository + item.source} className="text-link">
                View source ↗
              </a>
            </details>
          ))}
        </div>
      </div>
      <div className="engineering-evidence">
        <p>Explore the code, architecture notes and evaluation fixtures.</p>
        <a
          className="brand-button"
          href="https://github.com/vishalgwu/tento-agents"
        >
          View on GitHub <span aria-hidden="true">↗</span>
        </a>
        <a className="text-link" href={repository + "docs/ENGINEERING.md"}>
          Read the engineering deep dive ↗
        </a>
      </div>
    </section>
  );
}

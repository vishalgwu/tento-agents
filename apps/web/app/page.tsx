import Image from "next/image";
import Link from "next/link";
import { Brand, WorkspaceIcon } from "@/components/brand";
import { EngineeringSection } from "@/components/engineering-section";
import { workspaces, type Workspace } from "@/lib/workspaces";

const roles: Workspace[] = ["resident", "maintenance", "owner", "admin"];
const process = [
  {
    n: "01",
    title: "A few words. A clear beginning.",
    text: "Describe what needs attention. Your report is saved to your residence before the assessment begins.",
    tag: "RESIDENT INTAKE",
  },
  {
    n: "02",
    title: "Intelligence with a little more care.",
    text: "Safety rules screen the issue. AI organizes the details and checks applicable property evidence.",
    tag: "AI + POLICY EVIDENCE",
  },
  {
    n: "03",
    title: "Know what happens next.",
    text: "See the saved assessment and its limits. Supported in-house plans can create an internal work order.",
    tag: "VISIBLE OUTCOMES",
  },
];
export default function HomePage() {
  return (
    <main className="marketing">
      <header className="site-header">
        <Brand />
        <nav aria-label="Platform navigation">
          <a href="#engineering">Engineering</a>
          <a href="#workspaces">Workspaces</a>
          <Link href="/sign-in" className="nav-signin">
            Sign in <span aria-hidden="true">↗</span>
          </Link>
        </nav>
      </header>
      <section className="brand-hero">
        <div className="hero-copy">
          <p className="eyebrow">
            <span className="status-dot" /> Thoughtfully connected living
          </p>
          <h1>
            Good places.
            <br />
            <em>Better</em> living.
          </h1>
          <p className="hero-intro">
            A little less friction.
            <br />A lot more feeling at home.
          </p>
          <p className="hero-description">
            Meet Tento. One considered space for residents, maintenance teams
            and property owners — with AI that helps turn everyday issues into
            clearer next steps.
          </p>
          <div className="hero-actions">
            <a href="#workspaces" className="brand-button">
              Find your workspace <span aria-hidden="true">↗</span>
            </a>
            <a href="#approach" className="text-link">
              Get to know Tento <span aria-hidden="true">↓</span>
            </a>
          </div>
          <div className="hero-footnote">
            <span className="tiny-grid" aria-hidden="true">
              ▦
            </span>
            <p>
              Built around people.
              <br />
              <strong>Grounded in evidence.</strong>
            </p>
          </div>
        </div>
        <div className="hero-art">
          <div className="hero-photo">
            <Image
              src="/images/tento-courtyard.png"
              alt="Sunlit apartment courtyard with warm stone facades and leafy trees"
              fill
              priority
              sizes="(max-width: 900px) 100vw, 55vw"
              className="courtyard-image"
            />
            <span className="photo-label">SPACE TO FEEL AT HOME.</span>
          </div>
          <div className="hero-seal" aria-hidden="true">
            t
            <span>
              CONNECTED
              <br />
              BY DESIGN
            </span>
          </div>
          <div className="hero-note">
            <span className="note-icon" aria-hidden="true">
              ↗
            </span>
            <div>
              <p>From a small concern</p>
              <strong>to a clearer next step.</strong>
            </div>
            <span className="note-line" aria-hidden="true" />
          </div>
        </div>
      </section>
      <div className="brand-strip">
        <p>A shared place for every part of your community.</p>
        <div>
          <span>Residents</span>
          <i aria-hidden="true">✳</i>
          <span>Maintenance</span>
          <i aria-hidden="true">✳</i>
          <span>Owners</span>
          <i aria-hidden="true">✳</i>
          <span>Administrators</span>
        </div>
      </div>
      <section id="workspaces" className="workspace-section">
        <div className="section-intro">
          <div>
            <p className="eyebrow">Make yourself at home</p>
            <h2>
              Your community.
              <br />
              <em>Your way in.</em>
            </h2>
          </div>
          <p>
            Different perspectives. One connected experience.
            <br />
            Choose your workspace and sign in with your organization account.
          </p>
        </div>
        <div className="workspace-grid">
          {roles.map((key, i) => (
            <Link
              key={key}
              href={`/sign-in?workspace=${key}`}
              className="workspace-card"
            >
              <div className="workspace-card-top">
                <WorkspaceIcon kind={key} />
                <span>0{i + 1}</span>
              </div>
              <h3>{workspaces[key].name}</h3>
              <p>{workspaces[key].description}</p>
              <div className="workspace-card-bottom">
                <span>Enter workspace</span>
                <span className="round-arrow" aria-hidden="true">
                  ↗
                </span>
              </div>
            </Link>
          ))}
        </div>
        <p className="section-aside">
          One secure sign-in. Access shaped by your verified account role.
        </p>
      </section>
      <section id="approach" className="approach-section">
        <div className="approach-heading">
          <p className="eyebrow">A more considered kind of AI</p>
          <h2>
            Less chasing.
            <br />
            <em>More clarity.</em>
          </h2>
          <p>
            Technology should make everyday living feel simpler. Our GenAI
            maintenance workflow keeps the important things connected — the
            resident's words, the property's policies, and the next step.
          </p>
          <a href="#workspaces" className="text-link">
            Step inside <span aria-hidden="true">↗</span>
          </a>
        </div>
        <div className="process-list">
          {process.map((step) => (
            <article key={step.n}>
              <span className="process-number">{step.n}</span>
              <div>
                <p className="process-tag">{step.tag}</p>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </div>
            </article>
          ))}
        </div>
      </section>
      <EngineeringSection />
      <section className="honesty-section">
        <span className="honesty-mark" aria-hidden="true">
          ✳
        </span>
        <div>
          <p className="eyebrow">Confidence comes from honesty</p>
          <h2>
            Clear about what we know.
            <br />
            <em>Careful about what we don't.</em>
          </h2>
          <p>
            When approved policy evidence is missing, Tento says so. Reports
            stay saved, and unsupported plans stop safely. No invented policies.
            No claimed visits without a real confirmation.
          </p>
        </div>
      </section>
      <section className="closing-section">
        <p className="eyebrow">A better everyday starts here</p>
        <h2>
          A place for <em>everyone.</em>
        </h2>
        <a href="#workspaces" className="brand-button brand-button--lime">
          Find your workspace <span aria-hidden="true">↗</span>
        </a>
        <span className="closing-watermark" aria-hidden="true">
          tento
        </span>
      </section>
      <footer className="site-footer">
        <div className="footer-top">
          <Brand />
          <p>
            Thoughtful technology.
            <br />
            More connected communities.
          </p>
          <a href="#workspaces" className="text-link">
            Your workspace ↗
          </a>
        </div>
        <div className="footer-bottom">
          <p>Tento Resident OS · AI-assisted community maintenance</p>
          <p>
            Current release: resident reporting and read-only staff workspaces.
          </p>
        </div>
        <details className="scope-details">
          <summary>About this release</summary>
          <p>
            Approved property policies are needed for policy-backed work orders.
            Maintenance, owner and administrator workspaces display saved
            records. Repair assignment, vendor contact, financial reporting and
            user administration are outside this MVP. Architectural imagery is
            an original brand illustration, not a representation of a listed
            property.
          </p>
        </details>
      </footer>
    </main>
  );
}

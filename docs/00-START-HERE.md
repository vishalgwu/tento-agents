# Resident OS — Enterprise Blueprint

**A YC-quality, production-grade AI operating system for apartment communities.**
Working codename in this document: **Resident OS**. Internal engineering name for the AI spine: **the Ops Brain**.

Prepared: July 2026. Author of record: Vishal Fulsundar.

---

## How to read this

| File | What's in it | Read if you are |
|---|---|---|
| `00-START-HERE.md` | This file. Verdicts, scope cuts, the one-paragraph pitch. | Everyone |
| `01-strategy-and-product.md` | YC problem statement, segments, competitive analysis, MVP definition, user journeys, roadmap, what's cut and why | Investor / PM / you at 2am wondering if this is real |
| `02-ai-architecture.md` | Multi-agent design, Council Mode (redesigned), context engineering, RAG, memory, guardrails, judge, gateway, MCP, model matrix, token economics | The AI engineering interview |
| `03-platform-engineering.md` | Schema, API, monorepo, frontend, backend, infra, CI/CD, security, observability, evals, reliability, scaling 100 → 1M | The systems interview |
| `04-execution-and-career.md` | 12-week roadmap, milestones, demo plan, investor narrative, recruiter flow, interview answers, resume bullets, risks | You, weekly |

---

## The one paragraph

Property management software records what happened. Nobody has built the layer that decides what to do next. Resident OS is that layer: an AI operations brain that sits on top of Yardi/Entrata/AppFolio/Buildium and runs the workflows those systems only log — starting with the maintenance loop, which is the highest-frequency, most legally consequential, and most measurable workflow in the building. Every decision it makes is grounded in retrieved policy, checked by deterministic guardrails, scored for confidence, and written to an immutable audit record that can be replayed in a fair-housing deposition. The bet: in a regulated vertical, **the auditable AI wins, not the fastest AI.**

---

## Ten verdicts, up front

These are the decisions I'd defend in front of a YC partner, a staff engineer, and a fair-housing attorney. Full reasoning lives in the linked files.

**1. Cut 16 modules to one workflow. Ship the Maintenance Loop.**
Not because the vision is wrong, but because the vision is unfalsifiable until one loop works end to end. Maintenance is the correct first loop for a reason most people miss: **it is the only apartment workflow with abundant, cheap ground truth.** A human re-classifies the priority, a vendor accepts or rejects, the ticket reopens or doesn't. That means you can measure your agents instead of demoing them. → `01`

**2. Council Mode as specified would burn money and buy less accuracy than you think.**
Three specialists reasoning "independently" over the *same context* with the *same model* produce **correlated errors** — they agree confidently and wrongly. The fix is that council members must differ in **evidence**, not in persona: one grounded in SOP/policy, one in this unit's history, one in cost/vendor/warranty reality. Then disagreement is informative. Council fires on ~10% of tickets, not all. → `02`

**3. Read-parallel, write-single-threaded.**
Cognition's "Don't Build Multi-Agents" and Anthropic's multi-agent research post are usually framed as opposites; the 2026 synthesis is that they aren't. Parallel subagents are safe when they *read* and return compressed findings, and dangerous when they *write*, because conflicting implicit decisions can't be merged. So: many read agents, exactly one writer — the orchestrator — holding all side-effecting tools. → `02`

**4. LangGraph. Not CrewAI, not AutoGen.**
AutoGen is effectively in maintenance mode with Microsoft pointing users at Agent Framework; starting there in 2026 is a liability. CrewAI is faster to a demo and worse at recovery when an agent dies mid-run. You need durable checkpointing, explicit state, and a human-in-the-loop interrupt primitive — those are LangGraph's actual product. → `02`

**5. Don't buy a memory vendor yet. Ninety percent of "memory" here is a database row.**
Mem0/Zep/LangMem solve fuzzy episodic recall for open-ended assistants. In this domain the durable facts are *structured and authoritative*: unit 4B's water heater is a 2019 Rheem under warranty until March 2027. That belongs in Postgres with an effective date, not in a vector blob that a summarizer might mangle. Build a four-store memory service behind an interface; keep Mem0 as a swappable adapter. → `02`

**6. Don't build an AI gateway. Buy the boring one and build the policy layer.**
"Gateway" in your spec is really two things: a *transport* concern (multi-provider, fallback, retries, cost logging) and a *policy* concern (which model, what context budget, which retrieval strategy, cache or not). Transport is solved — self-hosted LiteLLM, one container. Policy is your product and should be your code. Building both is how you spend six weeks writing a proxy nobody interviews you about. → `02`

**7. Compliance is the wedge, not a feature.**
Every vendor says their system is compliant; what they usually mean is they put "do not discriminate" in a system prompt. That is not compliance. Fair-housing testing organizations can now run dozens of protected-class probes at a leasing bot remotely in an afternoon and build an evidentiary record. Your differentiator is that **every AI action ships with its evidence**: prompt hash, model version, retrieved citations with IDs, guardrail verdicts, confidence, and who approved it. That artifact is simultaneously your enterprise moat, your demo money-shot, and your best AI-safety engineering story. → `01`, `02`

**8. The Wellness Agent is a Phase-3 retention story and is 80% not-AI.**
Interest matching, scheduling, RSVP, reminders, attendance — that's a constraint solver and a notification engine with a thin LLM layer for planning and copy. It matters for the builder pitch (retention, community, "more than buildings"), and it is the wrong place to prove AI engineering depth. Also: design it so it **never stores health data**. Activity participation is fine; "attended the diabetes screening camp" is a liability you don't want on your servers. → `01`

**9. The Smart Notification Platform is core infrastructure and must be deterministic.**
An LLM must never decide *whether* to page someone at 2am. Eligibility, urgency, quiet hours, batching, fatigue budgets, retry, and escalation are a policy engine with a state machine. The LLM writes the words inside an approved template. Ship a simplified version in the MVP because every other module depends on it. → `02`

**10. Your reliability budget is about five LLM steps.**
A chain of N steps at 95% per-step reliability lands at 0.95^N end-to-end: ten steps is ~60%. This single line of arithmetic should drive every architecture decision — it's why the critical path is short, why deterministic steps replace LLM steps wherever possible, and why the interesting engineering is in *abstention* (knowing when to stop and ask a human) rather than in longer chains. → `02`, `03`

---

## Reconciling this with the plan you already have

You're building a community platform with a friend — interest groups, rich profiles, a marketplace, manager-vetted services, ratings — with AI in Phase 2. This blueprint does not throw that away. It reorders it, for one reason:

**The community app is a distribution and data wedge. The maintenance loop is the AI-engineering proof.** They serve different masters. The community app is what you sell to a builder in Pune or a mid-market operator in Virginia. The maintenance loop is what makes a hiring manager at a frontier lab or an FDE team stop scrolling.

Your job search is live *now*. So the sequencing in `04` is:

- **Weeks 1–4:** maintenance loop vertical slice, deployed, with a public eval report. This is the recruiter artifact.
- **Weeks 5–8:** evals, guardrails, Council, judge, dashboards. This is the interview artifact.
- **Weeks 9–12:** community surface + marketplace on the same schema, plus notifications. This is the customer artifact and your friend's parallel track.

One repo, two surfaces, one spine. The community modules reuse the notification engine, the RLS schema, and the audit log — so nothing is wasted, and neither of you is blocked on the other.

---

## What "done" looks like in 12 weeks

- A deployed product at a real URL with demo accounts for `resident`, `manager`, `owner`.
- A maintenance loop that triages, grounds, checks, decides, and escalates — with a visible trace for every decision.
- A **public eval report** with real numbers on a human-labeled golden set: routing accuracy, priority F1, groundedness, escalation precision/recall, cost per ticket, p50/p95 latency. Numbers you can defend line by line, including the bad ones.
- An observability stack where a stranger can click one ticket and watch the whole reasoning replay.
- A README that a busy person understands in 90 seconds.

If you get all of that and nothing else, this project has done its job.

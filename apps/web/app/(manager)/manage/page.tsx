import { ApprovalQueue, type PreviewApproval } from "./approval-queue";

export const metadata = { title: "Approval queue" };

const previewApprovals = [
  {
    approval_id: "c9ed39ab-9a67-4c6d-9e25-97c539425d0a",
    citation_verified: true,
    claims: [
      {
        citation: {
          excerpt:
            "The resident reported an active drip beneath the kitchen sink and supplied a photo at 08:42.",
          id: "resident-report",
          label: "Resident report",
        },
        text: "The resident reported an active drip beneath the kitchen sink.",
      },
      {
        citation: {
          excerpt:
            "Internal SOP 4.2 routes active water leaks to plumbing within the same business day.",
          id: "leak-sop",
          label: "SOP 4.2",
        },
        text: "The proposed same-day plumbing route follows the applicable SOP.",
      },
      {
        text: "Parts availability is expected before noon.",
      },
    ],
    decision_id: "89f0599a-ef89-4d08-90c1-f5d1d01a55cb",
    estimated_cost_cents: 24500,
    priority: "p1",
    proposed_responsible_party: "Harbor Plumbing",
    proposed_trade: "Plumbing",
    requested_at: "2030-01-16T08:50:00Z",
    required_role: "property_manager",
    sla_expires_at: "2030-01-16T16:50:00Z",
    symptom_summary: "Active kitchen-sink leak below the cabinet.",
    ticket_id: "1839d4b0-4d84-42de-89df-511ef840bf68",
    ticket_number: 1042,
    title: "Kitchen leak needs a same-day decision",
  },
  {
    approval_id: "d85f50db-6df4-4e2d-b43a-37fcf0929f0e",
    citation_verified: true,
    claims: [
      {
        citation: {
          excerpt:
            "The resident described intermittent cooling and a thermostat reading of 78°F at 18:14.",
          id: "hvac-report",
          label: "Resident report",
        },
        text: "The resident reported intermittent cooling with a 78°F thermostat reading.",
      },
      {
        citation: {
          excerpt:
            "The property maintenance log shows the last HVAC preventive service was completed 91 days ago.",
          id: "service-log",
          label: "Maintenance log",
        },
        text: "The unit is due for an HVAC diagnostic visit under the maintenance interval.",
      },
    ],
    decision_id: "c74f94d7-9801-485c-a421-d1c0a6abde99",
    estimated_cost_cents: 18900,
    priority: "p2",
    proposed_responsible_party: "Northside Mechanical",
    proposed_trade: "HVAC",
    requested_at: "2030-01-16T18:24:00Z",
    required_role: "asset_owner",
    sla_expires_at: "2030-01-17T18:24:00Z",
    symptom_summary: "Intermittent cooling in a resident-occupied unit.",
    ticket_id: "728e8244-9fc4-4bfa-a515-dcb83c76b5ec",
    ticket_number: 1046,
    title: "HVAC diagnostic exceeds the owner threshold",
  },
] satisfies readonly PreviewApproval[];

export default function ManagerWorkspacePage() {
  return <ApprovalQueue items={previewApprovals} />;
}

import type { Metadata } from "next";

import { ReportWizard } from "./report-wizard";

export const metadata: Metadata = {
  title: "Report a maintenance issue",
  description: "A guided, mobile-first maintenance report draft.",
};

/**
 * The interactive form is isolated in a Client Component because it manages
 * local photo selection and step state. No request is made from this route:
 * the public ticket-creation contract has not yet been accepted.
 */
export default function ResidentReportPage() {
  return <ReportWizard />;
}

import { TicketDetails } from "./ticket-details";
export const metadata = { title: "Maintenance request" };
export default async function TicketPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <TicketDetails id={id} />;
}

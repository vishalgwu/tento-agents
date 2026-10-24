import { PageFrame } from "@/components/page-frame";
import { SignInForm } from "@/components/sign-in-form";
import { isWorkspace, workspaces } from "@/lib/workspaces";

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ workspace?: string }>;
}) {
  const query = await searchParams;
  const workspace = isWorkspace(query.workspace) ? query.workspace : "resident";
  return (
    <PageFrame
      eyebrow="Secure workspace access"
      title={`${workspaces[workspace].name} sign in`}
      description={workspaces[workspace].description}
    >
      <SignInForm workspace={workspace} />
    </PageFrame>
  );
}

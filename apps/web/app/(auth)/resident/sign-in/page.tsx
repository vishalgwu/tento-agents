import { PageFrame } from "@/components/page-frame";
import { SignInForm } from "@/components/sign-in-form";
export default function ResidentSignInPage() {
  return <PageFrame eyebrow="Resident access" title="Resident sign in" description="Use your community account to report an issue and follow its assessment."><SignInForm workspace="resident" /></PageFrame>;
}

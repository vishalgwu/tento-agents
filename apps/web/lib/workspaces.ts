export const workspaces = {
  resident: {
    name: "Resident",
    path: "/app/report",
    roles: ["resident"],
    description: "Report an issue and follow your saved assessment.",
  },
  maintenance: {
    name: "Maintenance",
    path: "/maintenance",
    roles: ["maintenance_technician", "property_manager", "operations_admin"],
    description:
      "See your organization's requests, priorities, and agent assessments.",
  },
  owner: {
    name: "Owner",
    path: "/owner",
    roles: ["asset_owner", "property_manager", "operations_admin"],
    description: "See maintenance across your authorized organization.",
  },
  admin: {
    name: "Technical administrator",
    path: "/admin",
    roles: ["operations_admin"],
    description:
      "Inspect service readiness and recorded agent execution outcomes.",
  },
} as const;
export type Workspace = keyof typeof workspaces;
export function isWorkspace(value: unknown): value is Workspace {
  return typeof value === "string" && Object.hasOwn(workspaces, value);
}
export function canEnter(workspace: Workspace, role: string): boolean {
  return (workspaces[workspace].roles as readonly string[]).includes(role);
}
export function defaultWorkspace(role: string): Workspace | null {
  if (role === "operations_admin") return "admin";
  return (
    (Object.keys(workspaces) as Workspace[]).find((key) =>
      canEnter(key, role),
    ) ?? null
  );
}
export type Identity = { org_id: string; person_id: string; role: string };
export function isIdentity(value: unknown): value is Identity {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (
    typeof item.org_id === "string" &&
    typeof item.person_id === "string" &&
    typeof item.role === "string"
  );
}

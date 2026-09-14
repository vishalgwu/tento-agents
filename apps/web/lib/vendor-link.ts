import { createHmac, timingSafeEqual } from "node:crypto";

export type VendorLinkClaim = {
  expiresAt: number;
  vendorId: string;
  workOrderId: string;
};

/**
 * Verifies a vendor-only, no-account link of the form
 * `base64url(JSON payload).base64url(HMAC-SHA-256(payload))`.
 *
 * Tokens are validated on the server and fail closed when their secret is not
 * configured. Link creation belongs to the future authorised dispatch flow.
 */
export function verifyVendorLink(token: string): VendorLinkClaim | null {
  const secret = process.env.VENDOR_LINK_SIGNING_SECRET;
  if (!secret || !secret.trim()) {
    return null;
  }

  const [encodedPayload, encodedSignature, extraSegment] = token.split(".");
  if (!encodedPayload || !encodedSignature || extraSegment) {
    return null;
  }

  let payload: Buffer;
  let suppliedSignature: Buffer;
  try {
    payload = Buffer.from(encodedPayload, "base64url");
    suppliedSignature = Buffer.from(encodedSignature, "base64url");
  } catch {
    return null;
  }

  if (
    payload.length === 0 ||
    payload.toString("base64url") !== encodedPayload ||
    suppliedSignature.length !== 32 ||
    suppliedSignature.toString("base64url") !== encodedSignature
  ) {
    return null;
  }

  const expectedSignature = createHmac("sha256", secret).update(encodedPayload).digest();
  if (!timingSafeEqual(expectedSignature, suppliedSignature)) {
    return null;
  }

  try {
    const claim: unknown = JSON.parse(payload.toString("utf8"));
    if (!isVendorLinkClaim(claim) || claim.expiresAt <= Math.floor(Date.now() / 1000)) {
      return null;
    }

    return claim;
  } catch {
    return null;
  }
}

function isVendorLinkClaim(value: unknown): value is VendorLinkClaim {
  if (!value || typeof value !== "object") {
    return false;
  }

  const claim = value as Record<string, unknown>;
  return (
    typeof claim.workOrderId === "string" &&
    claim.workOrderId.trim().length > 0 &&
    typeof claim.vendorId === "string" &&
    claim.vendorId.trim().length > 0 &&
    typeof claim.expiresAt === "number" &&
    Number.isSafeInteger(claim.expiresAt)
  );
}

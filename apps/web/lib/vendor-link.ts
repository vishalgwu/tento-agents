import { createHmac, timingSafeEqual } from "node:crypto";

const MAX_VENDOR_LINK_TOKEN_LENGTH = 4_096;
const MAX_VENDOR_LINK_PAYLOAD_BYTES = 3_072;
const MAX_VENDOR_LINK_IDENTIFIER_LENGTH = 255;
const MAX_VENDOR_LINK_EXPIRY_SECONDS = 8_640_000_000_000;

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
  if (!secret || !secret.trim() || token.length > MAX_VENDOR_LINK_TOKEN_LENGTH) {
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
    payload.length > MAX_VENDOR_LINK_PAYLOAD_BYTES ||
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
    isOpaqueIdentifier(claim.workOrderId) &&
    isOpaqueIdentifier(claim.vendorId) &&
    typeof claim.expiresAt === "number" &&
    Number.isSafeInteger(claim.expiresAt) &&
    claim.expiresAt > 0 &&
    claim.expiresAt <= MAX_VENDOR_LINK_EXPIRY_SECONDS
  );
}

function isOpaqueIdentifier(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= MAX_VENDOR_LINK_IDENTIFIER_LENGTH &&
    value === value.trim() &&
    value.length > 0 &&
    !/[\u0000-\u001F\u007F]/.test(value)
  );
}

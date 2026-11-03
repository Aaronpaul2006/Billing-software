/**
 * The product's name and public contact details, in one place.
 *
 * PLACEHOLDERS (owner decision 2026-11-03): replace the name, tagline and
 * contact details before going live, and then remove `noindex` from
 * index.html so search engines may list the home page.
 */
export const BRAND = {
  name: "SiteLedger",
  tagline: "Billing for builders and contractors",
  description:
    "GST invoices, RA bills against your BOQ, payments, retention and TDS, with a portal for your clients.",
  contact: {
    phone: "+91 90000 00000",
    whatsapp: "919000000000", // digits only, for wa.me links
    email: "hello@example.com",
  },
} as const;

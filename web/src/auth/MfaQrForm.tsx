import { ShieldCheck } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import type { MfaEnrolment } from "./mfaEnrolment";

/** Start → scan the QR code (or type the key) → enter the 6-digit code. */
export function MfaQrForm({ enrolment }: { enrolment: MfaEnrolment }) {
  const { setup, enable, code, setCode } = enrolment;
  if (!setup.data) {
    return (
      <div>
        <Button
          onClick={() => {
            setup.mutate();
          }}
          disabled={setup.isPending}
        >
          <ShieldCheck aria-hidden /> Start
        </Button>
      </div>
    );
  }
  return (
    <form
      className="grid max-w-sm gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        enable.mutate();
      }}
    >
      <div className="flex justify-center rounded-md bg-white p-4">
        <QRCodeSVG value={setup.data.otpauth_uri} size={180} title="Authenticator QR code" />
      </div>
      <p className="text-muted-foreground text-sm">
        Scan the code, or enter this key:{" "}
        <code className="font-mono break-all">{setup.data.secret}</code>
      </p>
      <div className="grid gap-2">
        <Label htmlFor="mfa-code">6-digit code</Label>
        <Input
          id="mfa-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={code}
          onChange={(e) => {
            setCode(e.target.value);
          }}
        />
      </div>
      <Button type="submit" disabled={enable.isPending || !/^\d{6}$/.test(code.trim())}>
        Turn on
      </Button>
    </form>
  );
}

export function RecoveryCodes({ codes }: { codes: string[] }) {
  return (
    <ul
      aria-label="Recovery codes"
      className="bg-muted grid max-w-sm grid-cols-2 gap-2 rounded-md p-4 font-mono text-sm"
    >
      {codes.map((c) => (
        <li key={c}>{c}</li>
      ))}
    </ul>
  );
}

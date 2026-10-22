import { useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ApiError } from "@/api/problem";
import { useAuth } from "@/auth/context";
import { Body, Button, Notice, TextField, Title } from "@/components/ui";
import { space, useColors } from "@/theme";

function message(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "invalid_credentials":
        return "Email or password is wrong.";
      case "invalid_mfa_code":
        return "That code did not work. Check the time on your phone and try again.";
      case "invalid_mfa_token":
        return "The sign-in took too long. Start again.";
      case "no_active_membership":
        return "Your account is not active in any company.";
      default:
        return error.status === 0
          ? "Could not reach the server. Check your connection and try again."
          : error.message;
    }
  }
  return "Could not reach the server. Check your connection and try again.";
}

const CODE = /^(\d{6}|[A-Za-z0-9-]{8,20})$/;

/** Email and password, then the 2-step code when the account has one. */
export function SignInScreen() {
  const c = useColors();
  const { login, verifyMfa } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const signIn = async () => {
    setError(null);
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setBusy(true);
    try {
      const outcome = await login(email.trim(), password);
      if (outcome.kind === "mfa") setMfaToken(outcome.mfaToken);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    if (!mfaToken) return;
    setError(null);
    const value = code.replace(/\s/g, "");
    if (!CODE.test(value)) {
      setError("Enter the 6-digit code or a recovery code.");
      return;
    }
    setBusy(true);
    try {
      await verifyMfa(mfaToken, /^\d{6}$/.test(value) ? { code: value } : { recovery_code: value });
    } catch (e) {
      setError(message(e));
      if (e instanceof ApiError && e.code === "invalid_mfa_token") {
        setMfaToken(null);
        setCode("");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={[styles.fill, { backgroundColor: c.background }]}>
      <KeyboardAvoidingView
        style={styles.fill}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
          <Title>{mfaToken ? "Two-step verification" : "Sign in"}</Title>
          {error && <Notice text={error} />}
          {mfaToken ? (
            <View style={styles.form}>
              <TextField
                label="Code"
                hint="The 6-digit code from your authenticator app, or a recovery code."
                value={code}
                onChangeText={setCode}
                autoComplete="one-time-code"
                textContentType="oneTimeCode"
                autoCapitalize="none"
                autoCorrect={false}
                autoFocus
                onSubmitEditing={() => void verify()}
              />
              <Button label="Verify" busy={busy} onPress={() => void verify()} />
              <Button
                label="Start again"
                variant="ghost"
                onPress={() => {
                  setMfaToken(null);
                  setCode("");
                  setError(null);
                }}
              />
            </View>
          ) : (
            <View style={styles.form}>
              <TextField
                label="Email"
                value={email}
                onChangeText={setEmail}
                autoComplete="email"
                textContentType="username"
                keyboardType="email-address"
                autoCapitalize="none"
                autoCorrect={false}
              />
              <TextField
                label="Password"
                value={password}
                onChangeText={setPassword}
                autoComplete="current-password"
                textContentType="password"
                secureTextEntry
                onSubmitEditing={() => void signIn()}
              />
              <Button label="Sign in" busy={busy} onPress={() => void signIn()} />
              <Body muted>
                New here? Create your company on the web app first, then sign in with the same
                email.
              </Body>
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  page: { padding: space.xl, gap: space.lg, flexGrow: 1, justifyContent: "center" },
  form: { gap: space.lg },
});

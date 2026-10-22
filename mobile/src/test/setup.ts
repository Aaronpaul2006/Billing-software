import { configure } from "@testing-library/react-native";

import { resetSessionForTests } from "@/auth/session";

import { assertAllHandled, installApi } from "./api";
import { secureStore } from "./secureStore";

jest.mock(
  "expo-secure-store",
  () => jest.requireActual<typeof import("./secureStore")>("./secureStore").mockModule,
);

configure({ asyncUtilTimeout: 5000 });

beforeEach(() => {
  installApi();
  secureStore.clear();
});

afterEach(() => {
  resetSessionForTests();
  assertAllHandled(); // an unexpected API call fails the test
});

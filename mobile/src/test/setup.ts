import { configure } from "@testing-library/react-native";

import { resetSessionForTests } from "@/auth/session";

import { assertAllHandled, installApi } from "./api";
import { secureStore } from "./secureStore";

jest.mock(
  "expo-secure-store",
  () => jest.requireActual<typeof import("./secureStore")>("./secureStore").mockModule,
);

// Icon fonts load through the asset registry, which Jest does not have.
jest.mock("@expo/vector-icons/Ionicons", () => ({ __esModule: true, default: () => null }));

configure({ asyncUtilTimeout: 5000 });

beforeEach(() => {
  installApi();
  secureStore.clear();
});

afterEach(() => {
  resetSessionForTests();
  assertAllHandled(); // an unexpected API call fails the test
});

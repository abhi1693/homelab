import { Code, ConnectError } from "@zitadel/client";
import { afterEach, expect, it, vi } from "vitest";
import { retryNotFound } from "./retry-not-found";

afterEach(() => vi.useRealTimers());

it("recovers when a newly created user's projection becomes visible", async () => {
  vi.useFakeTimers();
  const operation = vi.fn().mockRejectedValueOnce(new ConnectError("missing", Code.NotFound)).mockResolvedValue("session");
  const result = retryNotFound(operation);
  await vi.advanceTimersByTimeAsync(500);
  await expect(result).resolves.toBe("session");
  expect(operation).toHaveBeenCalledTimes(2);
});

it("never retries rejected authentication or consumed identity intents", async () => {
  const error = new ConnectError("invalid intent", Code.PermissionDenied);
  const operation = vi.fn().mockRejectedValue(error);
  await expect(retryNotFound(operation)).rejects.toBe(error);
  expect(operation).toHaveBeenCalledTimes(1);
});

it("bounds missing-user retries and preserves the final error", async () => {
  vi.useFakeTimers();
  const error = new ConnectError("missing", Code.NotFound);
  const operation = vi.fn().mockRejectedValue(error);
  const assertion = expect(retryNotFound(operation)).rejects.toBe(error);
  await vi.runAllTimersAsync();
  await assertion;
  expect(operation).toHaveBeenCalledTimes(4);
});

import { Code, ConnectError } from "@zitadel/client";

/** Retry only a missing projection immediately after a successful identity write. */
export async function retryNotFound<T>(operation: () => Promise<T>): Promise<T> {
  const delays = [500, 1000, 2000];
  for (let attempt = 0; ; attempt++) {
    try {
      return await operation();
    } catch (error) {
      if (!(error instanceof ConnectError) || error.code !== Code.NotFound || attempt >= delays.length) {
        throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, delays[attempt]));
    }
  }
}

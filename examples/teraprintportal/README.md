# Connecting Jarvis to TeraPrintPortal

The `teraPrintPortal` builtin tool reads business data (clients, projects,
quotes, invoices, payments, appointments, sales, subscriptions, dashboard
summary) from a self-hosted TeraPrintPortal deployment through a single
key-protected endpoint. The portal side needs a one-file install.

## Portal side (once)

1. Copy `api-jarvis-route.ts` into the portal repository as
   `src/app/api/jarvis/route.ts`.
2. Allow the route through the Clerk middleware — in `src/middleware.ts`,
   add it to the public routes (the route enforces its own API key):

   ```ts
   const isPublicRoute = createRouteMatcher([
     "/sign-in(.*)",
     "/sign-up(.*)",
     "/invite/(.*)",
     "/api/webhooks/(.*)",
     "/api/stripe/webhook",
     "/api/jarvis",        // key-protected Jarvis bridge
   ]);
   ```

3. Set a strong shared secret as the `JARVIS_API_KEY` environment variable
   on the deployment (e.g. in Coolify → your app → Environment Variables),
   then redeploy.

## Jarvis side

In Jarvis settings (🔗 App Integrations), set:

| Setting | Value |
|---------|-------|
| TeraPrintPortal URL | The portal's base URL, e.g. `https://app.example.com` |
| TeraPrintPortal API Key | The same value as `JARVIS_API_KEY` |

Then ask Jarvis things like "how is my business doing?", "any unpaid
invoices?", or "what appointments do I have coming up?".

## Security notes

- The bridge is read-only and selects only non-sensitive columns
  (no invitation tokens, Stripe ids, or Clerk ids).
- The key comparison is timing-safe; requests without a valid
  `x-api-key` header get a 403.
- If `JARVIS_API_KEY` is unset on the portal, the endpoint refuses all
  requests.

# What the Pokit Note server and app need for Claude

The plugin in this repository is only half of the Claude integration. These changes live in the pokitnote.com server and the Pokit Note iPhone app. Until they ship, Claude sign-in and the Claude routine webhook will not work, even though the plugin installs and loads.

References:
- Claude connector authentication: https://claude.com/docs/connectors/building/authentication
- Routine API trigger: https://platform.claude.com/docs/en/api/claude-code/routines-fire

## 1. OAuth on pokitnote.com

The Cursor plugin used a pre-registered client, `grok-bot`, and scope `notes`. Claude does not use a pre-registered client by default. It registers itself, and it uses different redirect URIs.

### Client registration

Support at least one:

- **Client ID Metadata Document (CIMD), preferred.** Advertise `"client_id_metadata_document_supported": true` and include `"none"` in `token_endpoint_auth_methods_supported` in the authorization server metadata. Claude uses CIMD only when both are present.
- **Dynamic Client Registration (DCR).** Expose a `registration_endpoint` that accepts `application/json`. When tested against a local stand-in server, Claude Code 2.1.312 requested `/register` after discovery.

### Redirect URIs

Accept both of these:

- `https://claude.ai/api/mcp/auth_callback`, used by Claude on the web, the desktop app, mobile, and Claude routines.
- Claude Code's loopback redirect, `http://localhost:<any port>/callback` and `http://127.0.0.1:<any port>/callback`. The port changes every session, so match these with the port ignored.

On the consent screen, show the redirect URI's host clearly.

### Discovery

- Answer an unauthenticated request to `https://pokitnote.com/mcp` with **`401`**, not `200`, and `WWW-Authenticate: Bearer resource_metadata="<protected resource metadata URL>", scope="notes"`.
- In the protected resource metadata, `resource` must be exactly `https://pokitnote.com/mcp`, with no trailing slash, and `authorization_servers` must list the issuer first.
- Serve authorization server metadata at the issuer's `/.well-known/oauth-authorization-server` or `/.well-known/openid-configuration`. Claude Code also probes `/.well-known/oauth-protected-resource/mcp` and `/.well-known/oauth-protected-resource` on the MCP host.

The plugin's `.mcp.json` also requests scope `notes`, so Claude Code asks for it even if the server does not advertise it. Claude on the web uses the `scope` in the `401` or `scopes_supported`.

### Token endpoint

- Require S256 PKCE and advertise `"code_challenge_methods_supported": ["S256"]`.
- Accept `application/x-www-form-urlencoded` on `/token`.
- Rotate refresh tokens for public clients, and return the new one in the same response.
- Return `invalid_grant` for a refresh token that no longer works.
- Respond within 10 seconds for discovery, registration, and token requests, and within 30 seconds for refresh.
- Allow Anthropic's outbound range, `160.79.104.0/21`, through any firewall in front of the MCP and authorization servers.

## 2. Connected Assistant webhook in the iPhone app

Claude routines take a different request from Grok Bot routines. Add a **Claude** choice to Account → Connected Assistant that sends events this way.

### Request

```
POST https://api.anthropic.com/v1/claude_code/routines/<trig_id>/fire
Authorization: Bearer <routine token, sk-ant-oat01-...>
anthropic-version: 2026-10-21
Content-Type: application/json

{"text": "<the event JSON, as one string>"}
```

- The person pastes the full URL and the token. The app adds `Bearer `, the `anthropic-version` header, and the JSON body.
- `text` is the only field Claude reads. Serialize the existing event (`type`, `id`, `data`, `text`) to a JSON string and send it as `text`. It must be 65,536 characters or fewer.
- A `200` response has `claude_code_session_url`. The app can show it, or link to it, so the person can open the run.

### Retries

The endpoint has no idempotency key. **Every successful request starts a new run**, and each run starts fresh, so the skill cannot skip an `id` it already handled.

- Do not retry after a `200`.
- Retry `500` and `503` with exponential backoff.
- On `429`, wait for `Retry-After`.
- Do not retry `400`, `401`, `403`, or `404`. Show the person what to fix: `401` means the token is wrong or was replaced, `404` means the routine is gone, and `400` can mean the routine is paused.

### Rate limits

A routine accepts 30 runs an hour, and an account 100 runs an hour across all routines. Shares are fine, but change notices can easily pass that. Consider:

- Change notices off by default for Claude.
- Coalescing several `item_changed` events for the same item within a few minutes into one run.
- Dropping `item_changed` events, not shares, when the app sees `429`.

### Send Test

Send Test should send a `test` event the same way. A `200` means the URL and token work. The routine's reply appears in the run at claude.ai/code, not in the app.

## 3. Listing in the Claude directory (optional)

To list Pokit Note in Claude's connector directory, so people can connect it without typing the URL, submit it through the developer portal at https://claude.ai/directory/manage. The OAuth requirements above apply there too.

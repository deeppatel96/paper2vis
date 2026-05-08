# Deploying paper2vis

There are 4 services: **Clerk → Supabase → Railway → Vercel**. Do them in this order.

---

## 1. Clerk — Authentication

1. Go to [clerk.com](https://clerk.com) → **Sign up** → **Create application**
2. Name it `paper2vis`, enable **Email** sign-in → **Create application**
3. You land on the API Keys page. Copy these two immediately:
   - **Publishable key** — starts with `pk_live_...`
   - **Secret keys** → click "Secret keys" tab → copy the key starting with `sk_live_...`
4. Get your JWKS URL:
   - Left sidebar → **Configure → Domains**
   - You'll see a **Frontend API URL** like `https://happy-dog-12.clerk.accounts.dev`
   - Your `CLERK_JWKS_URL` = that URL + `/.well-known/jwks.json`
   - Example: `https://happy-dog-12.clerk.accounts.dev/.well-known/jwks.json`

**Don't set up the webhook yet — you need the Railway URL first.**

---

## 2. Supabase — Database

1. Go to [supabase.com](https://supabase.com) → **New project**
   - Name: `paper2vis`
   - Generate a database password and save it
   - Pick a region close to you → **Create new project** (~2 min)

2. Once ready: left sidebar → **SQL Editor** → **New query**
   - Paste the entire contents of [supabase/schema.sql](../supabase/schema.sql) → **Run**
   - Should say "Success. No rows returned"

3. Get your credentials: left sidebar → **Project Settings → API**
   - Copy **Project URL** → `https://xxxxxxxx.supabase.co` — this is `SUPABASE_URL`
   - Under "Project API keys" copy the **service_role** key (the long one, not the anon key) — this is `SUPABASE_SERVICE_ROLE_KEY`

---

## 3. Railway — Backend

1. Go to [railway.app](https://railway.app) → **Login with GitHub**
2. **New Project → Deploy from GitHub repo**
   - If no repos appear: click **Configure GitHub App** at the bottom → on GitHub select **Only select repositories** → pick `paper2vis` → **Save** → go back to Railway
3. Select the `paper2vis` repo — Railway will detect the Dockerfile and start a build
4. Click on the service that appears → **Variables** tab → add all of these:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your Anthropic key |
| `OPENAI_API_KEY` | your OpenAI key |
| `CLERK_JWKS_URL` | e.g. `https://happy-dog-12.clerk.accounts.dev/.well-known/jwks.json` |
| `CLERK_WEBHOOK_SECRET` | leave blank for now |
| `SUPABASE_URL` | `https://xxxxxxxx.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | the service_role key from Supabase |
| `ADMIN_SECRET` | make up any secret string, e.g. `my-admin-secret-123` |
| `FRONTEND_URL` | leave blank for now |
| `LLM_PROVIDER` | `openai` |
| `CODEGEN_PROVIDER` | `openai` |

5. Click the service → **Settings** tab → **Start Command** — make sure it is **completely empty** (the Dockerfile handles it)

6. Wait for the build to finish (~10 min first time — LaTeX is large). Once deployed, click **Settings → Networking → Generate Domain** to get a public URL like `https://paper2vis-api.up.railway.app`

**Now go back to Clerk and add the webhook:**
- Clerk dashboard → **Configure → Webhooks** → **Add Endpoint**
- URL: `https://paper2vis-api.up.railway.app/api/webhooks/clerk`
- Subscribe to events: check **user.created** and **user.deleted** → **Create**
- On the next screen copy the **Signing Secret** starting with `whsec_...`
- Go back to Railway → **Variables** → add `CLERK_WEBHOOK_SECRET` = `whsec_...` → Railway redeploys automatically

---

## 4. Vercel — Frontend

1. Go to [vercel.com](https://vercel.com) → **Add New Project** → import your GitHub repo
2. On the configuration screen:
   - **Framework Preset:** Next.js (auto-detected)
   - **Root Directory:** click **Edit** → type `web` → **Continue**
3. Under **Environment Variables** add these 3:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | your Railway URL, e.g. `https://paper2vis-api.up.railway.app` |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `pk_live_...` from Clerk Step 1 |
| `CLERK_SECRET_KEY` | `sk_live_...` from Clerk Step 1 |

4. **Deploy** — takes ~1 min. Your URL will be something like `https://paper2vis.vercel.app`

5. Go back to Railway → **Variables** → set `FRONTEND_URL` = `https://paper2vis.vercel.app`

---

## 5. Upgrade yourself to Pro

1. Sign up on your live site, then go to Clerk dashboard → **Users** → click your account → copy your **User ID** (starts with `user_`)
2. Run this in your terminal:

```bash
curl -X POST https://paper2vis-api.up.railway.app/api/admin/users/user_YOURCLERKID/tier \
  -H "x-admin-secret: YOUR_ADMIN_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"tier": "pro"}'
```

Should respond with `{"clerk_id": "user_...", "tier": "pro"}`

---

## Switching to a self-hosted server

When your home server is back online, only one change is needed:
- Vercel dashboard → your project → **Settings → Environment Variables** → update `NEXT_PUBLIC_API_URL` to your home server's public URL → **Redeploy**

---

## Checklist
- [ ] Clerk: app created, publishable key + secret key + JWKS URL saved
- [ ] Supabase: project created, schema.sql run, project URL + service_role key saved
- [ ] Railway: deployed, all env vars set, domain generated, start command cleared
- [ ] Clerk webhook pointing at Railway URL, `CLERK_WEBHOOK_SECRET` set in Railway
- [ ] Vercel: deployed with `web` as root directory, all 3 env vars set
- [ ] Railway `FRONTEND_URL` updated with Vercel URL
- [ ] Yourself upgraded to Pro via curl

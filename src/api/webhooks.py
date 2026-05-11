"""Clerk webhook handler — syncs users into Supabase on sign-up / deletion."""
from __future__ import annotations

import json
import os

from fastapi import Header, HTTPException, Request


def _supabase():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


async def handle_clerk_webhook(
    request: Request,
    svix_id: str = Header(default="", alias="svix-id"),
    svix_timestamp: str = Header(default="", alias="svix-timestamp"),
    svix_signature: str = Header(default="", alias="svix-signature"),
):
    payload = await request.body()

    # Verify Svix signature when secret is configured
    secret = os.environ.get("CLERK_WEBHOOK_SECRET", "")
    if secret:
        try:
            from svix.webhooks import Webhook
            Webhook(secret).verify(payload, {
                "svix-id": svix_id,
                "svix-timestamp": svix_timestamp,
                "svix-signature": svix_signature,
            })
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid signature: {exc}")

    event = json.loads(payload)
    event_type = event.get("type", "")
    data = event.get("data", {})

    if not os.environ.get("SUPABASE_URL"):
        return {"status": "ok", "note": "Supabase not configured"}

    sb = _supabase()

    if event_type in ("user.created", "user.updated"):
        clerk_id = data.get("id", "")
        emails = data.get("email_addresses") or []
        primary_id = data.get("primary_email_address_id")
        # Prefer primary email address; fall back to first in list
        email = ""
        for e in emails:
            if e.get("id") == primary_id:
                email = e.get("email_address", "")
                break
        if not email and emails:
            email = emails[0].get("email_address", "")
        if event_type == "user.created":
            sb.table("users").upsert({
                "clerk_id": clerk_id,
                "email": email,
                "tier": "mini",
            }).execute()
        else:
            # user.updated: only update email if we now have one
            if email:
                sb.table("users").update({"email": email}).eq("clerk_id", clerk_id).execute()

    elif event_type == "user.deleted":
        clerk_id = data.get("id", "")
        sb.table("usage").delete().eq("clerk_id", clerk_id).execute()
        sb.table("users").delete().eq("clerk_id", clerk_id).execute()

    return {"status": "ok"}

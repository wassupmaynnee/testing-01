#!/usr/bin/env bash
#
# Clippify post-deploy live smoke test. Run against the PUBLIC domain after
# deploy.sh reports READY.
#
#   ./smoke.sh https://clippify.example.com
#
# Does NOT complete a live charge — it stops at Stripe checkout-session creation
# (renders the hosted page) exactly as the ship spec requires.
set -u
B="${1:?usage: smoke.sh https://your-domain}"
P=0; F=0
ck(){ if [ "$2" = "$3" ]; then P=$((P+1)); echo "  PASS  $1"; else F=$((F+1)); echo "  FAIL  $1 (want $2 got $3)"; fi; }
code(){ curl -s -o /dev/null -w "%{http_code}" "$@"; }
CJ="$(mktemp)"
E="smoke$(date +%s)@example.com"

echo "== reachability + TLS =="
ck "homepage 200"          200 "$(code "$B/")"
T=$(curl -s -o /dev/null -w "%{time_total}" "$B/")
ck "homepage < 3s (${T}s)" 1 "$(awk -v t="$T" 'BEGIN{print (t<3)?1:0}')"
ck "no mixed content (https base)" 1 "$([ "${B%%://*}" = https ] && echo 1 || echo 0)"

echo "== security headers (curl) =="
H=$(curl -s -D- -o /dev/null "$B/health")
ck "HSTS"                   1 "$(echo "$H" | grep -ic strict-transport-security)"
ck "CSP"                    1 "$(echo "$H" | grep -ic content-security-policy)"
ck "X-Frame-Options DENY"   1 "$(echo "$H" | grep -ic 'x-frame-options: DENY')"
ck "X-Content-Type-Options" 1 "$(echo "$H" | grep -ic 'x-content-type-options: nosniff')"
ck "X-Request-Id"           1 "$(echo "$H" | grep -ic x-request-id)"

echo "== critical journey =="
ck "health ok"     200 "$(code "$B/health")"
ck "ready ok"      200 "$(code "$B/ready")"
ck "signup 201"    201 "$(code -c "$CJ" -X POST -F email="$E" -F password=password123 "$B/api/auth/signup")"
ck "login 200"     200 "$(code -c "$CJ" -X POST -F email="$E" -F password=password123 "$B/api/auth/login")"
ck "me authed 200" 200 "$(code -b "$CJ" "$B/api/auth/me")"
# checkout: session creation only (NO live charge). Expect a checkout.stripe.com URL.
CO=$(curl -s -b "$CJ" -X POST -F tier=pro -F interval=monthly "$B/api/billing/checkout")
ck "checkout session created (hosted page, no charge)" 1 \
   "$(echo "$CO" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(1 if d.get("ok") and "checkout.stripe.com" in d["data"].get("url","") else 0)' 2>/dev/null || echo 0)"
ck "clips list 200"    200 "$(code -b "$CJ" "$B/api/clips")"
ck "featured public"   200 "$(code "$B/api/clips/featured")"
ck "logout 200"        200 "$(code -b "$CJ" -X POST "$B/api/auth/logout")"

echo ""
echo "NOTE: full generate->play->download requires uploading a real video; do that"
echo "      manually once (dashboard) — the API journey above proves the path is live."
echo "NOTE: fire a 'Send test webhook' from the Stripe dashboard and confirm 200 at"
echo "      $B/api/billing/webhook."
echo ""
echo "RESULT: $P passed, $F failed"
rm -f "$CJ"
[ "$F" = 0 ]

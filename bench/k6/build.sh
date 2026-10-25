#!/usr/bin/env bash
# Build the k6 binary the bench uses: stock k6 plus the xk6-sse extension, so ask.js can
# follow /v1/jobs/{id}/events and time the first `token` event (stock k6's http module
# only returns a response once it has ended). k6's automatic extension resolution does
# not resolve k6/x/sse (it fails with "unknown dependency"), so this builds it with the
# official xk6 image. Output: bench/.bin/k6 (gitignored). Needs only Docker.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
K6_VERSION="${K6_VERSION:-v2.3.0}"
XK6_SSE_VERSION="${XK6_SSE_VERSION:-v0.2.0}"
XK6_IMAGE="${XK6_IMAGE:-grafana/xk6:1.4.15}"
OUT="$ROOT/bench/.bin"

case "$(uname -s)" in
  Darwin) goos=darwin ;;
  Linux) goos=linux ;;
  *) echo "unsupported OS $(uname -s)" >&2; exit 2 ;;
esac
case "$(uname -m)" in
  arm64 | aarch64) goarch=arm64 ;;
  x86_64 | amd64) goarch=amd64 ;;
  *) echo "unsupported arch $(uname -m)" >&2; exit 2 ;;
esac

mkdir -p "$OUT"
chmod 777 "$OUT" # the xk6 container writes as its own user
docker run --rm -e "GOOS=$goos" -e "GOARCH=$goarch" -v "$OUT:/xk6" "$XK6_IMAGE" \
  build "$K6_VERSION" --with "github.com/phymbert/xk6-sse@$XK6_SSE_VERSION"
"$OUT/k6" version

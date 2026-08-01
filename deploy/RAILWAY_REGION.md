# Prefer EU egress closer to Russian public tender hosts (zakupki.gov.ru, ETPs).
# US-west (sfo) frequently times out / empty-scrapes those sites.
#
# Change region (airport code, not GCP name):
#   railway api mutation with multiRegionConfig {"ams":{"numReplicas":1}}
#   or Dashboard → api → Settings → Regions → Amsterdam
#
# This project: api moved sfo → ams (2026-08-01). Postgres volume stays put.
# Optional: SCRAPE_PROXY_URL / HTTPS_PROXY for a RU datacenter proxy if EU still flaky.
# Keep HTTP_RU_READ_TIMEOUT ≤35 and HTTP_RETRIES≤2 so dead RU hosts don't starve the API.

# Prefer EU egress closer to Russian public tender hosts (zakupki.gov.ru, ETPs).
# US-west (sfo) frequently times out / empty-scrapes those sites.
# Change region: Railway Dashboard → api → Settings → Regions → Amsterdam (europe-west4)
# or GraphQL serviceInstanceUpdate with multiRegionConfig {"europe-west4":{"numReplicas":1}}.
# Optional: set SCRAPE_PROXY_URL / HTTPS_PROXY to a RU datacenter proxy if EU still flaky.

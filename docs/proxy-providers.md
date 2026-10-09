# Public proxy provider evaluation

Evaluation date: 9 October 2026, from the Animan development machine. These are connectivity observations, not worldwide reliability rankings.

## Sources and selection

| Provider | Primary documentation | Endpoint used by Animan | Reason for inclusion |
| --- | --- | --- | --- |
| ProxyScrape | [Official repository](https://github.com/proxyscrape/free-proxy-list) | `raw.githubusercontent.com/proxyscrape/free-proxy-list/main/proxies/protocols/https/data.json` | HTTPS CONNECT shard, structured metadata, official mirror, MIT repository. Provider documents a five-minute mirror refresh. |
| Proxifly | [Official repository](https://github.com/proxifly/free-proxy-list) | `raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/https/data.json` | HTTPS-capable subset, JSON, country/protocol shards. Provider documents five-minute updates. |
| Geonode | [Official free-list page](https://geonode.com/free-proxy-list) | `proxylist.geonode.com/api/proxy-list?limit=100&page=1&sort_by=lastChecked&sort_type=desc&protocols=http` | Separate provider/API, small recent-page fetch, structured entries. Its free-list page advertises minute updates. |

A fourth candidate, Monosans, could not be retrieved through the research browser during this evaluation and was not selected. Provider descriptions establish supported formats and refresh claims; Animan independently checks HTTPS access before choosing a proxy.

## Observed tests

The first run retrieved all three lists with verified TLS. Twelve addresses were sampled from each provider using a fixed seed. Each address was tested through a clean `curl_cffi` session against `https://api.ipify.org?format=json`, without source cookies, with strict certificate validation, no redirects and a six-second timeout. Tests ran with at most six simultaneous connections. Success required HTTP success and a JSON response containing a public IP.

| Provider / list | Valid entries parsed | Successful HTTPS tests | Successful response times |
| --- | ---: | ---: | --- |
| ProxyScrape / HTTPS CONNECT | 111 | 5 / 12 | 2,152–4,954 ms |
| Proxifly / HTTP | 3,000 (parser cap) | 0 / 12 | — |
| Geonode / HTTP | 100 | 0 / 12 | — |

A second run tested the HTTPS subset of Proxifly (1,011 parsed addresses), alongside the same ProxyScrape shard and a fresh Geonode page. All three returned 0 / 12 successful tests in that run. These results do not establish why each connection failed and do not demonstrate access to protected anime websites. They show that a successful provider-side check or one successful local check is insufficient to guarantee lasting connectivity.

ProxyScrape is the preferred discovery source for its targeted HTTPS data and the successes in the first run. Animan retains the other providers for diversity, but selection uses current locally measured health and latency, not the provider's reputation or reported total. No fetched entry becomes eligible before a local successful check. Previously fetched lists are retained on a provider fetch failure, while expired health is excluded from selection.

## Runtime behavior

- Lists refresh once per application launch or on user request. Source networking never fetches a public list while trying to render a page.
- While automatic rotation is enabled, health checks replenish a small candidate set when fewer than three fresh proxies remain, at most once every five minutes. Provider lists are not fetched on this interval.
- Refreshes are coalesced and run in the background. Provider URLs, sizes, list counts and concurrent tests are bounded.
- Public and imported lists accept public IP addresses only. This prevents lists from causing checks of localhost, LAN services or cloud metadata. A user's local or named proxy remains configurable in Manual.
- HTTPS is required for connectivity checks and public-proxy source connections, including if a legacy manual configuration disables certificate validation.
- Only recently successful proxies are eligible; health expires after 30 minutes. A failed website request does not claim the proxy is globally dead, and per-domain attempt history prevents repeatedly choosing it for that domain.
- Rotation skips different ports on the same proxy host and proxies reporting an exit IP already attempted for the domain, so changing a port alone is not presented as an address change.
- Automatic rotation is opt-in, limited to one retry before a response is exposed and two changes per domain per five minutes. Active transfers are not switched. A failed media read releases its connection before attempting rotation, then download recovery requests the saved offset or incomplete segment. Changing route drops cookies and connection handles for the affected domain; saved cookies are discarded at restart if the route fingerprint differs.
- A website may still reject all tested proxies or require human verification. A normal browser tab does not share its cookies automatically with Python.

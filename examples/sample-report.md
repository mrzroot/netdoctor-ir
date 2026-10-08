# netdoctor report

- **Generated:** 2026-10-08T10:10:13+00:00 (UTC)
- **netdoctor:** 0.1.0 · **Python:** 3.12.15 · **OS:** Linux 6.12.94+
- **Resolver used for scan:** system

## Developer services

**Healthy — all 38 developer services are reachable.**

- Your resolver returns fake-IP answers (198.18.0.0/15): a local proxy/VPN is intercepting DNS, so these results describe that proxy's path.

| Service | Host | Verdict | HTTP | Total | Why |
|---|---|---|---|---|---|
| PyPI (index) | `pypi.org` | **ok** | 200 | 271 ms |  |
| PyPI files | `files.pythonhosted.org` | **ok** | 404 | 233 ms | Package downloads are served from this CDN host. |
| npm registry | `registry.npmjs.org` | **ok** | 200 | 264 ms |  |
| Yarn registry | `registry.yarnpkg.com` | **ok** | 200 | 323 ms |  |
| jsDelivr CDN | `cdn.jsdelivr.net` | **ok** | 200 | 273 ms |  |
| Docker Hub registry | `registry-1.docker.io` | **ok** | 401 | 442 ms | 401 is normal here: the registry asks for a token. |
| Docker Hub auth | `auth.docker.io` | **ok** | 200 | 296 ms |  |
| Docker Hub website | `hub.docker.com` | **ok** | 200 | 341 ms |  |
| GitHub Container Registry | `ghcr.io` | **ok** | 401 | 338 ms |  |
| Quay.io | `quay.io` | **ok** | 401 | 545 ms |  |
| Kubernetes registry | `registry.k8s.io` | **ok** | 401 | 389 ms |  |
| Go module proxy | `proxy.golang.org` | **ok** | 200 | 266 ms |  |
| Go checksum DB | `sum.golang.org` | **ok** | 200 | 452 ms |  |
| go.dev | `go.dev` | **ok** | 200 | 618 ms |  |
| GitHub | `github.com` | **ok** | 200 | 304 ms |  |
| GitHub API | `api.github.com` | **ok** | 200 | 363 ms |  |
| GitHub raw content | `raw.githubusercontent.com` | **ok** | 200 | 229 ms |  |
| GitHub release downloads | `objects.githubusercontent.com` | **ok** | 404 | 82 ms |  |
| GitLab.com | `gitlab.com` | **ok** | 401 | 283 ms |  |
| Google Fonts CSS | `fonts.googleapis.com` | **ok** | 200 | 384 ms |  |
| Google Fonts files | `fonts.gstatic.com` | **ok** | 404 | 376 ms |  |
| Google Maven (Android) | `dl.google.com` | **ok** | 302 | 141 ms |  |
| Android Developers | `developer.android.com` | **ok** | 200 | 1366 ms |  |
| Firebase console | `firebase.google.com` | **ok** | 200 | 604 ms |  |
| Maven Central | `repo1.maven.org` | **ok** | 200 | 142 ms |  |
| Gradle distributions | `services.gradle.org` | **ok** | 200 | 157 ms |  |
| Ubuntu archive (apt) | `archive.ubuntu.com` | **ok** | 200 | 339 ms |  |
| Debian (apt) | `deb.debian.org` | **ok** | 200 | 274 ms |  |
| Alpine packages | `dl-cdn.alpinelinux.org` | **ok** | 200 | 377 ms |  |
| crates.io index | `index.crates.io` | **ok** | 200 | 247 ms |  |
| RubyGems | `rubygems.org` | **ok** | 200 | 154 ms |  |
| Packagist (Composer) | `repo.packagist.org` | **ok** | 200 | 294 ms |  |
| NuGet | `api.nuget.org` | **ok** | 200 | 171 ms |  |
| pub.dev (Dart/Flutter) | `pub.dev` | **ok** | 200 | 314 ms |  |
| Hugging Face | `huggingface.co` | **ok** | 200 | 269 ms |  |
| OpenAI API | `api.openai.com` | **ok** | 401 | 249 ms | 401 without an API key is normal; 403 'unsupported_country' is the sanction. |
| VS Code Marketplace | `marketplace.visualstudio.com` | **ok** | 200 | 275 ms |  |
| Stack Overflow | `stackoverflow.com` | **ok** | 302 | 182 ms |  |

## DNS resolvers

| # | Resolver | Kind | Address | Answered | Median | Score | Notes |
|---|---|---|---|---|---|---|---|
| 1 | Cloudflare | public | `1.0.0.1` | 24/24 | 8 ms | 100 | 2 rewritten/CDN-differing answer(s) |
| 2 | Google Public DNS | public | `8.8.4.4` | 24/24 | 13 ms | 99 | 4 rewritten/CDN-differing answer(s) |
| 3 | 403.online | anti-sanction | `10.202.10.202` | 0/24 | — | 0 | No answers — this resolver only serves Iranian networks. |
| 4 | AdGuard DNS | public | `94.140.14.14` | 0/24 | — | 0 | No answers — unreachable from this network. |
| 5 | Begzar | anti-sanction | `185.55.226.26` | 0/36 | — | 0 | No answers — this resolver only serves Iranian networks. |
| 6 | Control D (unfiltered) | public | `76.76.2.0` | 0/24 | — | 0 | No answers — unreachable from this network. |
| 7 | Electro | anti-sanction | `78.157.42.100` | 0/24 | — | 0 | No answers — this resolver only serves Iranian networks. |
| 8 | IranServer | anti-sanction | `172.29.2.100` | 0/24 | — | 0 | No answers — this resolver only serves Iranian networks. |
| 9 | OpenDNS | public | `208.67.222.222` | 0/24 | — | 0 | No answers — unreachable from this network. |
| 10 | Quad9 | public | `9.9.9.9` | 0/24 | — | 0 | No answers — unreachable from this network. |
| 11 | Radar Game | anti-sanction | `10.202.10.10` | 0/24 | — | 0 | No answers — this resolver only serves Iranian networks. |
| 12 | Shatel | isp | `85.15.1.14` | 0/24 | — | 0 | No answers — this resolver only serves Iranian networks. |
| 13 | Shecan (free) | anti-sanction | `178.22.122.100` | 0/24 | — | 0 | No answers — this resolver only serves Iranian networks. |

## Package mirrors

| Ecosystem | Mirror | URL | Verdict | Latency | Trust |
|---|---|---|---|---|---|
| pypi | PyPI (upstream) ★ | `https://pypi.org/simple` | **ok** | 86 ms | official |
| pypi | Liara PyPI | `https://package-mirror.liara.ir/repository/pypi/simple` | **slow** | 2088 ms | documented |
| pypi | Runflare PyPI | `https://mirror-pypi.runflare.com/simple` | **timeout** | 6020 ms | documented |
| pypi | Chabokan PyPI | `https://mirror2.chabokan.net/registry/pypi/simple` | **http-error** | 2371 ms | community-reported |
| pypi | Kargadan PyPI | `https://mirror.kargadan.ir/repository/pypi-group/simple` | **timeout** | 7061 ms | documented |
| pypi | Litebase PyPI | `https://mirror.litebase.ir/repository/pypi/simple` | **tcp-error** | 271 ms | community-reported |
| pypi | DevNeeds PyPI | `https://pypi.devneeds.ir/simple` | **http-error** | 1440 ms | community-reported |
| pypi | TUNA (Tsinghua) PyPI | `https://pypi.tuna.tsinghua.edu.cn/simple` | **ok** | 1968 ms | documented |
| npm | npm (upstream) ★ | `https://registry.npmjs.org` | **ok** | 59 ms | official |
| npm | Liara npm | `https://package-mirror.liara.ir/repository/npm` | **ok** | 1205 ms | documented |
| npm | Runflare npm | `https://mirror-npm.runflare.com` | **timeout** | 6017 ms | documented |
| npm | Chabokan npm | `https://mirror2.chabokan.net/registry/npm` | **http-error** | 1155 ms | community-reported |
| npm | Kargadan npm | `https://mirror.kargadan.ir/repository/npm-group` | **timeout** | 7078 ms | documented |
| npm | Litebase npm | `https://mirror.litebase.ir/repository/npm` | **tcp-error** | 273 ms | community-reported |
| npm | DevNeeds npm | `https://npm.devneeds.ir` | **slow** | 2066 ms | community-reported |
| npm | npmmirror | `https://registry.npmmirror.com` | **ok** | 709 ms | documented |
| docker | Docker Hub (upstream) ★ | `https://registry-1.docker.io` | **ok** | 184 ms | official |
| docker | ArvanCloud registry mirror | `https://docker.arvancloud.ir` | **ok** | 1077 ms | community-reported |
| docker | Liara registry mirror | `https://docker-mirror.liara.ir` | **ok** | 1489 ms | documented |
| docker | Runflare registry mirror | `https://mirror-docker.runflare.com` | **timeout** | 6004 ms | documented |
| docker | HamDocker | `https://hub.hamdocker.ir` | **ok** | 1846 ms | community-reported |
| docker | MobinHost registry mirror | `https://docker.mobinhost.com` | **timeout** | 6006 ms | community-reported |
| docker | Focker | `https://focker.ir` | **timeout** | 6455 ms | community-reported |
| docker | DevNeeds registry mirror | `https://docker.devneeds.ir` | **ok** | 913 ms | community-reported |
| docker | Kargadan registry mirror | `https://docker-mirror.kargadan.ir` | **ok** | 1422 ms | documented |
| go | proxy.golang.org (upstream) ★ | `https://proxy.golang.org` | **ok** | 50 ms | official |
| go | Liara GOPROXY | `https://package-mirror.liara.ir/repository/go` | **ok** | 1302 ms | documented |
| go | Runflare GOPROXY | `https://mirror-go.runflare.com` | **timeout** | 6004 ms | documented |
| go | Kargadan GOPROXY | `https://mirror.kargadan.ir/repository/go-group` | **timeout** | 6683 ms | documented |
| go | Litebase GOPROXY | `https://mirror.litebase.ir/repository/go` | **tcp-error** | 262 ms | community-reported |
| go | goproxy.io | `https://goproxy.io` | **ok** | 273 ms | documented |
| go | goproxy.cn | `https://goproxy.cn` | **slow** | 2260 ms | documented |
| maven | Maven Central (upstream) ★ | `https://repo1.maven.org/maven2` | **ok** | 46 ms | official |
| maven | Myket Maven | `https://maven.myket.ir` | **ok** | 974 ms | community-reported |
| maven | Runflare Maven | `https://mirror-maven.runflare.com/maven2` | **timeout** | 6005 ms | documented |
| maven | DevNeeds Maven | `https://maven.devneeds.ir` | **ok** | 1316 ms | community-reported |
| maven | Kargadan Maven | `https://mirror.kargadan.ir/repository/maven-central-group` | **ok** | 1380 ms | documented |

---

_Generated by [netdoctor-ir](https://github.com/mrzroot/netdoctor-ir) — a diagnostic tool; it measures, it does not bypass anything._

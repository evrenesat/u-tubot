// The committed preferences of every e2e profile: the manual proxy to the refusing proxy, and every Firefox service the
// plan's section 6 names turned off. The loopback addresses of the harness are the proxy's only exemptions.
// group: proxy
user_pref("network.proxy.type", 1);
user_pref("network.proxy.http", "127.0.0.1");
user_pref("network.proxy.http_port", __PROXY_PORT__);
user_pref("network.proxy.ssl", "127.0.0.1");
user_pref("network.proxy.ssl_port", __PROXY_PORT__);
user_pref("network.proxy.no_proxies_on", "127.0.0.1,127.0.0.2,127.0.0.3");
user_pref("network.proxy.allow_hijacking_localhost", false);
// group: updates
user_pref("app.update.auto", false);
user_pref("app.update.enabled", false);
user_pref("app.update.background.enabled", false);
user_pref("extensions.update.enabled", false);
user_pref("extensions.update.autoUpdateDefault", false);
user_pref("extensions.update.url", "");
user_pref("extensions.update.background.url", "");
// group: add-on metadata
user_pref("extensions.getAddons.cache.enabled", false);
user_pref("extensions.getAddons.showPane", false);
user_pref("extensions.getAddons.discovery.api_url", "");
// group: blocklist
user_pref("extensions.blocklist.enabled", false);
user_pref("extensions.blocklist.url", "");
// group: remote settings
user_pref("services.settings.server", "data:,#remote-settings-dummy/v1");
user_pref("services.settings.poll_interval", 0);
user_pref("services.settings.security.oneOffUpdates", false);
// group: telemetry and health report
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("toolkit.telemetry.unified", false);
user_pref("toolkit.telemetry.archive.enabled", false);
user_pref("browser.ping-centre.telemetry", false);
// group: Normandy and experiments
user_pref("app.normandy.enabled", false);
user_pref("app.normandy.api_url", "");
user_pref("app.shield.optoutstudies.enabled", false);
user_pref("browser.discovery.enabled", false);
user_pref("messaging-system.rsexperimentloader.enabled", false);
// group: safe browsing lists
user_pref("browser.safebrowsing.malware.enabled", false);
user_pref("browser.safebrowsing.phishing.enabled", false);
user_pref("browser.safebrowsing.downloads.enabled", false);
user_pref("browser.safebrowsing.downloads.remote.enabled", false);
user_pref("browser.safebrowsing.downloads.remote.url", "");
// group: captive-portal and connectivity checks
user_pref("network.captive-portal-service.enabled", false);
user_pref("network.connectivity-service.enabled", false);
// group: DNS over HTTPS
user_pref("network.trr.mode", 5);
user_pref("network.trr.uri", "");
user_pref("network.trr.custom_uri", "");
// group: DNS and link prefetch
user_pref("network.dns.disablePrefetch", true);
user_pref("network.dns.disablePrefetchFromHTTPS", true);
user_pref("network.prefetch-next", false);
user_pref("network.predictor.enabled", false);
user_pref("network.predictor.enable-prefetch", false);
// group: speculative connections
user_pref("network.http.speculative-parallel-limit", 0);
user_pref("browser.places.speculativeConnect.enabled", false);
// group: push service
user_pref("dom.push.enabled", false);
user_pref("dom.push.connection.enabled", false);
// group: new-tab content and sponsored tiles
user_pref("browser.newtabpage.enabled", false);
user_pref("browser.newtabpage.activity-stream.feeds.section.topstories", false);
user_pref("browser.newtabpage.activity-stream.feeds.topsites", false);
user_pref("browser.newtabpage.activity-stream.showSponsored", false);
user_pref("browser.newtabpage.activity-stream.showSponsoredTopSites", false);
user_pref("browser.newtabpage.activity-stream.asrouter.userprefs.cfr.addons", false);
user_pref("browser.newtabpage.activity-stream.asrouter.userprefs.cfr.features", false);
user_pref("browser.newtab.preload", false);
// group: search suggestions and search-engine updates
user_pref("browser.search.suggest.enabled", false);
user_pref("browser.urlbar.suggest.searches", false);
user_pref("browser.urlbar.quicksuggest.enabled", false);
user_pref("browser.urlbar.suggest.quicksuggest.nonsponsored", false);
user_pref("browser.urlbar.suggest.quicksuggest.sponsored", false);
user_pref("browser.search.update", false);
user_pref("browser.search.geoip.url", "");
// group: location services
user_pref("geo.enabled", false);
user_pref("geo.provider.network.url", "");
user_pref("geo.provider.msls.url", "");
user_pref("browser.region.network.url", "");
user_pref("browser.region.update.enabled", false);
// group: default browser and first-run pages
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("startup.homepage_welcome_url", "about:blank");
user_pref("browser.usedOnWindows10.introURL", "about:blank");
user_pref("browser.startup.homepage", "about:blank");
user_pref("browser.startup.page", 0);
// group: unrelated browser traffic
user_pref("extensions.pocket.enabled", false);
user_pref("services.sync.enabled", false);
user_pref("browser.tabs.firefox-view", false);
user_pref("browser.ml.enable", false);
user_pref("browser.contentblocking.category", "standard");
// group: test-only permission prompts and extension compat
user_pref("extensions.webextOptionalPermissionPrompts", false);
user_pref("extensions.install.requireBuiltInCerts", false);

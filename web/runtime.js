/* Clippify runtime loader — reads window.CLIPPIFY_CONFIG (served by /config.js,
   env-driven) and wires optional, privacy-respecting integrations. No secrets
   here: the Sentry DSN and Plausible domain are public values. */
(function () {
  var cfg = window.CLIPPIFY_CONFIG || {};

  // Privacy-friendly analytics (Plausible): no cookies, no PII. Skips entirely
  // when the visitor has Do-Not-Track enabled.
  var dnt = navigator.doNotTrack === "1" || window.doNotTrack === "1";
  if (cfg.plausibleDomain && !dnt) {
    var p = document.createElement("script");
    p.defer = true;
    p.setAttribute("data-domain", cfg.plausibleDomain);
    p.src = "https://plausible.io/js/script.js";
    document.head.appendChild(p);
  }

  // Front-end error & performance monitoring (Sentry browser SDK), only when a
  // DSN is configured.
  if (cfg.sentryDsn) {
    var s = document.createElement("script");
    s.src = "https://browser.sentry-cdn.com/7.120.0/bundle.tracing.min.js";
    s.crossOrigin = "anonymous";
    s.onload = function () {
      if (window.Sentry) {
        window.Sentry.init({
          dsn: cfg.sentryDsn,
          environment: cfg.appEnv || "production",
          tracesSampleRate: 0.1,
        });
      }
    };
    document.head.appendChild(s);
  }
})();

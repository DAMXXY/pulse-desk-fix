(() => {
  const transition = document.getElementById("page-transition");
  if (!transition) {
    return;
  }

  const message = transition.querySelector("[data-transition-message]");
  const loginPath = document.body.dataset.loginPath;
  const isLoginPage = document.body.dataset.loginPage === "true";

  function showTransition({ login = false, text }) {
    transition.classList.toggle("page-transition--login", login);
    transition.classList.add("is-visible");
    transition.setAttribute("aria-hidden", "false");
    message.textContent = text;
  }

  function isLocalNavigation(url) {
    return url.origin === window.location.origin &&
      !url.pathname.toLowerCase().endsWith(".csv");
  }

  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }

    const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!anchor || anchor.hasAttribute("download") || (anchor.target && anchor.target !== "_self")) {
      return;
    }

    const destination = new URL(anchor.href, window.location.href);
    if (!isLocalNavigation(destination) || destination.href === window.location.href) {
      return;
    }
    if (destination.pathname === window.location.pathname && destination.search === window.location.search && destination.hash) {
      return;
    }

    const login = isLoginPage || destination.pathname === loginPath;
    showTransition({
      login,
      text: destination.pathname === loginPath ? "Preparing secure sign-in" : "Loading workspace",
    });
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.hasAttribute("data-no-transition") || (form.target && form.target !== "_self")) {
      return;
    }

    const destination = new URL(form.action || window.location.href, window.location.href);
    if (!isLocalNavigation(destination)) {
      return;
    }

    const signingOut = destination.pathname.endsWith("/logout");
    showTransition({
      login: isLoginPage,
      text: signingOut ? "Signing out" : isLoginPage ? "Checking your sign-in" : "Saving your changes",
    });
  });

  window.addEventListener("pageshow", () => {
    transition.classList.remove("is-visible");
    transition.setAttribute("aria-hidden", "true");
  });
})();

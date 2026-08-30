/**
 * admin-layout.js - the mobile navigation drawer.
 *
 * From 992px up the sidebar is always visible and this script does nothing but
 * attach idle listeners. Below 992px admin.css turns the sidebar into an
 * off-canvas drawer that is translated off screen, and shown when the body
 * carries the class `sidebar-open`. Adding and removing that one class is this
 * file's whole job.
 *
 * Four ways to close it, because on a phone any of them is the natural one:
 *   - the X button in the drawer header
 *   - tapping the dark backdrop
 *   - following a nav link (you are leaving the page anyway)
 *   - widening the window past the desktop breakpoint
 */
document.addEventListener('DOMContentLoaded', function () {
  var body = document.body;
  var sidebar = document.querySelector('.sidebar');
  var toggleBtn = document.getElementById('sidebarToggleBtn');
  var closeBtn = document.getElementById('sidebarCloseBtn');
  var backdrop = document.getElementById('sidebarBackdrop');

  // The login page has no sidebar, and this script is harmless there.
  if (!sidebar || !toggleBtn || !backdrop) {
    return;
  }

  function openSidebar() {
    body.classList.add('sidebar-open');
  }

  function closeSidebar() {
    body.classList.remove('sidebar-open');
  }

  // The hamburger toggles rather than only opening, so tapping it twice closes.
  toggleBtn.addEventListener('click', function () {
    if (body.classList.contains('sidebar-open')) {
      closeSidebar();
      return;
    }
    openSidebar();
  });

  if (closeBtn) {
    closeBtn.addEventListener('click', closeSidebar);
  }

  backdrop.addEventListener('click', closeSidebar);

  // Escape is the expected key for dismissing an overlay.
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      closeSidebar();
    }
  });

  // Following a link closes the drawer so it is not still open behind the next
  // page if that page fails to load.
  sidebar.querySelectorAll('a.nav-link').forEach(function (link) {
    link.addEventListener('click', function () {
      if (window.innerWidth < 992) {
        closeSidebar();
      }
    });
  });

  // Rotating a tablet or dragging a window wider must not leave the page
  // locked behind an invisible backdrop: body.sidebar-open also sets
  // overflow: hidden.
  window.addEventListener('resize', function () {
    if (window.innerWidth >= 992) {
      closeSidebar();
    }
  });
});

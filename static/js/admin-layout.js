document.addEventListener('DOMContentLoaded', function () {
  var body = document.body;
  var sidebar = document.querySelector('.sidebar');
  var toggleBtn = document.getElementById('sidebarToggleBtn');
  var closeBtn = document.getElementById('sidebarCloseBtn');
  var backdrop = document.getElementById('sidebarBackdrop');

  if (!sidebar || !toggleBtn || !backdrop) {
    return;
  }

  function openSidebar() {
    body.classList.add('sidebar-open');
  }

  function closeSidebar() {
    body.classList.remove('sidebar-open');
  }

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

  sidebar.querySelectorAll('a.nav-link').forEach(function (link) {
    link.addEventListener('click', function () {
      if (window.innerWidth < 992) {
        closeSidebar();
      }
    });
  });

  window.addEventListener('resize', function () {
    if (window.innerWidth >= 992) {
      closeSidebar();
    }
  });
});

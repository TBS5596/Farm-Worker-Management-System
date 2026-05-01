document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#usersTable', {
    order: [[6, 'desc']],
    pageLength: 10,
    columnDefs: [{ orderable: false, targets: 7 }],
    language: { search: 'Search users:' },
  });

  FMSUI.onDelegatedClick('.reset-password-btn', function (resetBtn) {
    document.getElementById('resetPasswordForm').action = '/users/' + resetBtn.dataset.userId + '/reset-password';
    document.getElementById('resetPasswordUsername').textContent = resetBtn.dataset.username;
  });
});

/**
 * users-page.js - the Users table (administrators only).
 *
 * Column order:
 *   0 Username  1 Name    2 Role   3 Account  4 Linked Worker
 *   5 Email     6 Phone   7 Created  8 Actions
 *
 * "Account" shows whether the user is disabled, or still holding a temporary
 * password they must change at next login.
 */
document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#usersTable', {
    order: [[7, 'desc']],  // most recently created first
    pageLength: 10,
    columnDefs: [{ orderable: false, targets: 8 }],
    language: { search: 'Search users:' },
  });

  // Fills the reset-password confirmation modal. The new password is generated
  // server-side and shown once in a flash message - it is never sent to the
  // browser before the reset, so there is nothing to display here beyond the
  // username being reset.
  FMSUI.onDelegatedClick('.reset-password-btn', function (resetBtn) {
    document.getElementById('resetPasswordForm').action =
      '/users/' + resetBtn.dataset.userId + '/reset-password';
    document.getElementById('resetPasswordUsername').textContent = resetBtn.dataset.username;
  });
});

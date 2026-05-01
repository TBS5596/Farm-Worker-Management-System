document.addEventListener('DOMContentLoaded', function () {
  new DataTable('#workersTable', {
    order: [[9, 'desc']],
    pageLength: 10,
    columnDefs: [{ orderable: false, targets: 10 }],
    language: { search: 'Search workers:' },
  });

  // Event delegation handles buttons on all DataTables pages, not just the first
  document.addEventListener('click', function (e) {
    const resetBtn = e.target.closest('.reset-pin-btn');
    if (resetBtn) {
      document.getElementById('resetPinPk').value = resetBtn.dataset.workerId;
      document.getElementById('resetPinWorkerId').value = resetBtn.dataset.workerCode;
      document.getElementById('resetPinWorkerName').textContent = resetBtn.dataset.workerName;
      document.getElementById('resetPinWorkerCode').textContent = resetBtn.dataset.workerCode;
    }

    const editBtn = e.target.closest('.edit-worker-btn');
    if (editBtn) {
      document.getElementById('editWorkerPk').value = editBtn.dataset.workerId;
      document.getElementById('editWorkerId').value = editBtn.dataset.workerCode;
      document.getElementById('editWorkerCode').textContent = editBtn.dataset.workerCode;
      document.getElementById('editName').value = editBtn.dataset.name || '';
      document.getElementById('editPhone').value = editBtn.dataset.phone || '';
      document.getElementById('editAddress').value = editBtn.dataset.address || '';
      document.getElementById('editEmergency').value = editBtn.dataset.emergency || '';
      document.getElementById('editDepartment').value = editBtn.dataset.department || '';
      document.getElementById('editNrc').value = editBtn.dataset.nrc || '';
      document.getElementById('editStatus').value = editBtn.dataset.status || 'active';
      document.getElementById('editEnrollmentDate').value = editBtn.dataset.enrollmentDate || '';
    }
  });
});

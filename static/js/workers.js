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
      let record = {};
      try {
        record = JSON.parse(editBtn.getAttribute('data-record') || '{}');
      } catch (_) {
        record = {};
      }

      document.getElementById('editWorkerPk').value = record.id || 0;
      document.getElementById('editWorkerId').value = record.worker_id || '';
      document.getElementById('editWorkerCode').textContent = record.worker_id || '-';
      document.getElementById('editName').value = record.name || '';
      document.getElementById('editPhone').value = record.phone_number || '';
      document.getElementById('editAddress').value = record.address || '';
      document.getElementById('editEmergency').value = record.emergency_contact || '';
      document.getElementById('editDepartment').value = record.department || '';
      document.getElementById('editNrc').value = record.nrc_number || '';
      document.getElementById('editStatus').value = record.status || 'active';
      document.getElementById('editEnrollmentDate').value = record.enrollment_date || '';
    }
  });
});
